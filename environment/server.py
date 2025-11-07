import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .bash_session import BashSessionManager
from .base import ToolError
from .dinit_manager import ServiceLoader, SimpleDinit
from .file_ops import FileOpsManager
from .grading import GradingRunner

logger = logging.getLogger(__name__)

app = FastAPI()

bash_manager = BashSessionManager()
file_ops_manager = FileOpsManager()


class BashRequest(BaseModel):
    command: str | None = None
    restart: bool = False


class EditRequest(BaseModel):
    command: str
    path: str
    file_text: str | None = None
    view_range: list[int] | None = None
    old_str: str | None = None
    new_str: str | None = None
    insert_line: int | None = None


class GradeRequest(BaseModel):
    base: str
    test: str
    golden: str


class ToolResultResponse(BaseModel):
    output: str | None = None
    error: str | None = None
    base64_image: str | None = None
    system: str | None = None


class GradeResponse(BaseModel):
    success: bool
    result: dict[str, Any]


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/bash")
async def bash_execute(request: BashRequest) -> ToolResultResponse:
    try:
        result = await bash_manager.execute(command=request.command, restart=request.restart)
        return ToolResultResponse(
            output=result.output,
            error=result.error,
            base64_image=result.base64_image,
            system=result.system,
        )
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        logger.exception("Error executing bash command")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/edit")
async def edit_file(request: EditRequest) -> ToolResultResponse:
    try:
        result = await file_ops_manager.execute(
            command=request.command,
            path=request.path,
            file_text=request.file_text,
            view_range=request.view_range,
            old_str=request.old_str,
            new_str=request.new_str,
            insert_line=request.insert_line,
        )
        return ToolResultResponse(
            output=result.output,
            error=result.error,
            base64_image=result.base64_image,
            system=result.system,
        )
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        logger.exception("Error executing edit command")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/setup")
async def setup_dinit():
    try:
        logger.info("Starting dinit")
        loader = ServiceLoader(Path("/etc/dinit.d"))
        services = loader.load_all()
        engine = SimpleDinit(services)
        engine.start("boot")
        return {"status": "success"}
    except Exception as e:
        logger.exception("Error starting dinit")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/grade")
async def grade_solution(request: GradeRequest) -> GradeResponse:
    try:
        runner = GradingRunner(
            base=request.base,
            test=request.test,
            golden=request.golden,
        )
        success, result = runner.run_grading()
        return GradeResponse(success=success, result=result)
    except Exception as e:
        logger.exception("Error running grading")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate")
async def validate_patches(request: GradeRequest) -> GradeResponse:
    try:
        runner = GradingRunner(
            base=request.base,
            test=request.test,
            golden=request.golden,
        )
        success, result = runner.validate_patches()
        return GradeResponse(success=success, result=result)
    except Exception as e:
        logger.exception("Error validating patches")
        raise HTTPException(status_code=500, detail=str(e))
