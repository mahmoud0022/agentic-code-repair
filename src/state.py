from typing import TypedDict


class RepairState(TypedDict):
    bug_description: str
    file_path: str
    code: str
    analysis: str
    proposed_code: str
    test_output: str
    tests_passed: bool
    attempts: int
