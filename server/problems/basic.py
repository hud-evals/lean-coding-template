import logging

from server.spec import ProblemSpec, PROBLEM_REGISTRY

logger = logging.getLogger(__name__)


PROBLEM_REGISTRY.append(
    ProblemSpec(
        id="greet_len",
        description="Please complete the function greet_length without using `sorry`.",
        difficulty="easy",
        base="greet_len_baseline",
        test="greet_len_test",
        golden="greet_len_golden",
    )
)
