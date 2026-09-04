from langgraph.graph import END, START, StateGraph

from src.agents import analyzer_agent, fixer_agent, tester_agent
from src.state import RepairState

BUG_DESCRIPTION = (
    "The discount calculation is incorrect. A percentage discount should "
    "reduce the price by that percentage of the original price."
)
TARGET_FILE = "examples/buggy_calculator/calculator.py"
MAX_ATTEMPTS = 3


def _after_tester(state: RepairState) -> str:
    if state["tests_passed"]:
        return "end"
    if state["attempts"] < MAX_ATTEMPTS:
        return "retry"
    return "end"


def build_graph():
    graph = StateGraph(RepairState)

    graph.add_node("analyzer", analyzer_agent)
    graph.add_node("fixer", fixer_agent)
    graph.add_node("tester", tester_agent)

    graph.add_edge(START, "analyzer")
    graph.add_edge("analyzer", "fixer")
    graph.add_edge("fixer", "tester")
    graph.add_conditional_edges(
        "tester", _after_tester, {"retry": "fixer", "end": END}
    )

    return graph.compile()


def main():
    with open(TARGET_FILE, encoding="utf-8") as f:
        original_code = f.read()

    print("=== ORIGINAL CODE ===")
    print(original_code)

    initial_state: RepairState = {
        "bug_description": BUG_DESCRIPTION,
        "file_path": TARGET_FILE,
        "code": original_code,
        "analysis": "",
        "proposed_code": "",
        "test_output": "",
        "tests_passed": False,
        "attempts": 0,
    }

    graph = build_graph()
    final_state = graph.invoke(initial_state)

    print("=== ANALYZER ===")
    print(final_state["analysis"])

    print("=== FIXED CODE ===")
    print(final_state["proposed_code"])

    print("=== PYTEST RESULT ===")
    print(final_state["test_output"])

    print("=== FINAL STATUS ===")
    if final_state["tests_passed"]:
        print("REPAIR SUCCESSFUL")
    else:
        print("REPAIR FAILED")


if __name__ == "__main__":
    main()
