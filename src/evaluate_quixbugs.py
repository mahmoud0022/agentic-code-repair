import json
import shutil
import subprocess
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from src.agents import analyzer_agent, fixer_agent
from src.state import RepairState

QUIXBUGS_ROOT = Path("benchmark/QuixBugs")
WORK_ROOT = Path("results/quixbugs_work")
RESULTS_DIR = Path("results")

BUG_DESCRIPTION = (
    "The provided Python implementation contains a bug. Analyze the code "
    "and repair it so that the supplied tests pass."
)
MAX_ATTEMPTS = 3
PYTEST_TIMEOUT_SECONDS = 20
TIMEOUT_MESSAGE = "PYTEST TIMEOUT: exceeded 20 seconds"

# Simple, self-contained QuixBugs tasks previously identified as suitable
# for this small local evaluation (no dependency on other buggy modules
# such as node.py). Only these task names may be run.
ALLOWED_TASKS = [
    "gcd",
    "bitcount",
    "find_first_in_sorted",
    "is_valid_parenthesization",
    "possible_change",
    "to_base",
    "sieve",
    "pascal",
    "subsequences",
    "kth",
]

CONFTEST_CONTENT = """import pytest


def pytest_configure(config):
    pytest.use_correct = False
    pytest.run_slow = False
"""


def prepare_task_copy(task: str) -> dict:
    work_dir = WORK_ROOT / task
    if work_dir.exists():
        shutil.rmtree(work_dir)

    programs_dir = work_dir / "python_programs"
    testcases_dir = work_dir / "python_testcases"
    json_dir = work_dir / "json_testcases"
    programs_dir.mkdir(parents=True)
    testcases_dir.mkdir(parents=True)
    json_dir.mkdir(parents=True)

    source_file = programs_dir / f"{task}.py"
    shutil.copy2(QUIXBUGS_ROOT / "python_programs" / f"{task}.py", source_file)
    shutil.copy2(
        QUIXBUGS_ROOT / "python_testcases" / f"test_{task}.py",
        testcases_dir / f"test_{task}.py",
    )
    shutil.copy2(
        QUIXBUGS_ROOT / "python_testcases" / "load_testdata.py",
        testcases_dir / "load_testdata.py",
    )
    shutil.copy2(
        QUIXBUGS_ROOT / "json_testcases" / f"{task}.json",
        json_dir / f"{task}.json",
    )
    (work_dir / "conftest.py").write_text(CONFTEST_CONTENT, encoding="utf-8")

    return {
        "work_dir": work_dir,
        "source_file": source_file,
        "test_rel_path": f"python_testcases/test_{task}.py",
    }


def run_pytest_safe(work_dir: Path, test_rel_path: str) -> tuple[bool, str]:
    """Run pytest for one test file with a hard timeout.

    A hung test must never hang the whole evaluator, so a timeout is
    treated as a failed test rather than propagating the exception.
    """
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", test_rel_path, "-q"],
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=PYTEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, TIMEOUT_MESSAGE

    output = result.stdout + result.stderr
    return result.returncode == 0, output


def make_safe_tester_agent(test_rel_path: str, work_dir: Path):
    def tester_agent(state: RepairState) -> dict:
        passed, output = run_pytest_safe(work_dir, test_rel_path)
        return {"test_output": output, "tests_passed": passed}

    return tester_agent


def build_graph(tester_agent):
    def after_tester(state: RepairState) -> str:
        if state["tests_passed"]:
            return "end"
        if state["attempts"] < MAX_ATTEMPTS:
            return "retry"
        return "end"

    graph = StateGraph(RepairState)
    graph.add_node("analyzer", analyzer_agent)
    graph.add_node("fixer", fixer_agent)
    graph.add_node("tester", tester_agent)

    graph.add_edge(START, "analyzer")
    graph.add_edge("analyzer", "fixer")
    graph.add_edge("fixer", "tester")
    graph.add_conditional_edges(
        "tester", after_tester, {"retry": "fixer", "end": END}
    )

    return graph.compile()


def evaluate_task(task: str) -> dict:
    copy_info = prepare_task_copy(task)
    work_dir = copy_info["work_dir"]
    source_file = copy_info["source_file"]
    test_rel_path = copy_info["test_rel_path"]

    print("=== QUIXBUGS TASK ===")
    print(f"Task: {task}")
    print()

    initial_passed, initial_output = run_pytest_safe(work_dir, test_rel_path)

    print("=== INITIAL TEST ===")
    print(f"Result: {'PASSED' if initial_passed else 'FAILED'}")
    print(initial_output)
    print()

    if initial_passed:
        print("=== ANALYZER ===")
        print("Analysis: (skipped - initial test already passed)")
        print()
        print("=== REPAIR ===")
        print("Attempts: 0")
        print()
        print("=== FINAL TEST ===")
        print("Result: PASSED")
        print()
        print("=== FINAL STATUS ===")
        print("REPAIR SUCCESSFUL")

        return {
            "task_name": task,
            "initial_tests_failed": False,
            "analyzer_summary": "",
            "repair_attempts": 0,
            "final_tests_passed": True,
            "final_pytest_output": initial_output,
        }

    tester_agent = make_safe_tester_agent(test_rel_path, work_dir)
    graph = build_graph(tester_agent)

    initial_state: RepairState = {
        "bug_description": BUG_DESCRIPTION,
        "file_path": str(source_file),
        "code": source_file.read_text(encoding="utf-8"),
        "analysis": "",
        "proposed_code": "",
        "test_output": initial_output,
        "tests_passed": False,
        "attempts": 0,
    }

    final_state = graph.invoke(initial_state)

    print("=== ANALYZER ===")
    print(f"Analysis: {final_state['analysis']}")
    print()
    print("=== REPAIR ===")
    print(f"Attempts: {final_state['attempts']}")
    print()
    print("=== FINAL TEST ===")
    print(f"Result: {'PASSED' if final_state['tests_passed'] else 'FAILED'}")
    print(final_state["test_output"])
    print()
    print("=== FINAL STATUS ===")
    print("REPAIR SUCCESSFUL" if final_state["tests_passed"] else "REPAIR FAILED")

    return {
        "task_name": task,
        "initial_tests_failed": True,
        "analyzer_summary": final_state["analysis"],
        "repair_attempts": final_state["attempts"],
        "final_tests_passed": final_state["tests_passed"],
        "final_pytest_output": final_state["test_output"],
    }


def _print_allowed_tasks():
    print("Allowed tasks:")
    for name in ALLOWED_TASKS:
        print(f"  {name.upper()}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m src.evaluate_quixbugs <TASK_NAME>")
        _print_allowed_tasks()
        sys.exit(1)

    task = sys.argv[1].strip().lower()

    if task not in ALLOWED_TASKS:
        print(f"'{sys.argv[1]}' is not an allowed task.")
        _print_allowed_tasks()
        sys.exit(1)

    result = evaluate_task(task)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"quixbugs_{task}.json"
    result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
