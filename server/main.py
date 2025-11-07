import asyncio
import logging
import os

import click
import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

import server.problems
from server.utils import import_submodules

from .spec import PROBLEM_REGISTRY, Grade, ProblemSpec

logger = logging.getLogger(__name__)

mcp = FastMCP("agent_evaluation", log_level="DEBUG", debug=True)

TEST_MODE = os.environ.get("MCP_TESTING_MODE", "1") in ["1", "true"]

http_client = httpx.AsyncClient(base_url="http://localhost:8000", timeout=120.0)

if TEST_MODE:
    @mcp.tool(
        name="str_replace_editor",
        description="Create and edit files using str_replace_editor.  Please use absolute paths for all file names.",
    )
    async def str_replace_editor(
        *,
        command: str,
        path: str,
        file_text: str | None = None,
        view_range: list[int] | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
    ) -> dict:
        response = await http_client.post(
            "/edit",
            json={
                "command": command,
                "path": path,
                "file_text": file_text,
                "view_range": view_range,
                "old_str": old_str,
                "new_str": new_str,
                "insert_line": insert_line,
            },
        )
        if response.status_code != 200:
            error_detail = response.json().get("detail", "Unknown error")
            return {"error": error_detail}
        data = response.json()
        return {k: v for k, v in data.items() if v is not None}

    @mcp.tool(
        name="bash",
        description="Run bash commands. If you need to restart the bash session, set restart to true.",
    )
    async def bash(*, command: str, restart: bool = False) -> dict:
        response = await http_client.post(
            "/bash",
            json={"command": command, "restart": restart},
        )
        if response.status_code != 200:
            error_detail = response.json().get("detail", "Unknown error")
            return {"error": error_detail}
        data = response.json()
        return {k: v for k, v in data.items() if v is not None}

import_submodules(server.problems)


template = """
You will be working on a task for example-lean-codebase.
The repository has already been cloned in the environment in /home/ubuntu/example-lean-codebase.
Lean has been installed, please source ~/.bash_profile to use it.

Use the tools provided to complete the following task:

<STATEMENT>
"""

def spec_to_statement(spec: ProblemSpec) -> str:
    """
    Convert a problem spec to a statement.
    """
    hints_enabled = os.environ.get("HINTS", "none").lower() in ["all"]
    statement = spec.description

    if hints_enabled and len(spec.hints) > 0:
        hint_text = ""
        for hint_spec in spec.hints:
            hint_text += f"\n - {hint_spec.text}\n"
        statement += "\n\n" + f"<HINTS>{hint_text}</HINTS>"
    return template.replace("<STATEMENT>", statement)


def _get_spec(problem_id: str) -> ProblemSpec:
    for spec in PROBLEM_REGISTRY:
        if spec.id == problem_id:
            return spec
    raise ValueError(f"No problem found for id: {problem_id}")


@mcp.tool()
async def setup_problem(
    problem_id: str = Field(description="The id of the problem to solve"),
) -> str:
    """Starts the enviroment and returns the problem statement"""
    spec = _get_spec(problem_id)

    logger.info(f"=== SETUP_PROBLEM DEBUG ===")
    logger.info(f"Problem ID: {problem_id}")
    logger.info(f"Spec: {spec}")

    response = await http_client.post("/setup")
    if response.status_code != 200:
        raise RuntimeError(f"Failed to setup dinit: {response.text}")

    return spec_to_statement(spec)


@click.command()
@click.argument("problem_id")
def setup_problem_script(problem_id: str):
    """Set up a problem environment and return the problem statement."""
    statement = asyncio.run(setup_problem(problem_id))
    print(statement)


@mcp.tool()
async def grade_problem(
    problem_id: str,
    transcript: str | int = Field(description="The entire transcript produced by the model and its tool calls"),
) -> Grade:
    """Check your solution for grading. Returns a Grade object making sure to include all components that make up the score as subscores."""

    spec = _get_spec(problem_id)

    response = await http_client.post(
        "/grade",
        json={"base": spec.base, "test": spec.test, "golden": spec.golden},
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to grade problem: {response.text}")

    data = response.json()
    success = data["success"]
    result = data["result"]

    if success:
        logger.info("Grading successful!")
    else:
        logger.error("Grading failed!")

    grade = Grade(
        subscores={"Tests": 1.0 if success else 0.0},
        weights={"Tests": 1.0},
        metadata=result,
    )

    return grade


@click.command()
@click.argument("problem_id", envvar="PROBLEM_ID")
@click.option("--output_path", default="/tmp/grade_junit.xml", help="Path to output the JUNIT XML file")
def grade_problem_script(
    problem_id: str,
    output_path: str = None,
):
    """Grade a problem solution and return the grade results."""
    transcript = "dummy transcript"
    grade = asyncio.run(grade_problem(problem_id, transcript))
    with open(output_path, "w") as f:
        f.write(grade.metadata["junit"])
    print(grade)



async def validate_problem(problem_id: str) -> tuple[bool, dict[str, any]]:
    """Validate the test and golden patches for a problem."""

    spec = _get_spec(problem_id)

    if not spec.base:
        raise ValueError(f"Problem {problem_id} missing base branch/commit")
    if not spec.test:
        raise ValueError(f"Problem {problem_id} missing test branch/commit")
    if not spec.golden:
        raise ValueError(f"Problem {problem_id} missing golden branch/commit")

    logger.info("=== VALIDATE_PROBLEM DEBUG ===")
    logger.info(f"Problem ID: {problem_id}")
    logger.info(f"Base: {spec.base}")
    logger.info(f"Test: {spec.test}")
    logger.info(f"Golden: {spec.golden}")

    response = await http_client.post(
        "/validate",
        json={"base": spec.base, "test": spec.test, "golden": spec.golden},
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to validate patches: {response.text}")

    data = response.json()
    success = data["success"]
    result = data["result"]

    if success:
        logger.info("Validation successful!")
    else:
        logger.error("Validation failed!")

    if "junit" in result:
        print("\nJUnit XML Result:")
        print(result["junit"])

    return success, result



@click.command()
@click.argument("problem_id", envvar="PROBLEM_ID")
@click.option("--output_path", default="/tmp/validate_junit.xml", help="Path to output the JUNIT XML file")
def validate_problem_script(
    problem_id: str,
    output_path: str = None,
):
    """Validate a problem solution and return the validation results."""
    asyncio.run(validate_problem(problem_id))

@click.command()
def main():
    mcp.run(transport="stdio")
