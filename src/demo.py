import shutil
from pathlib import Path

import gradio as gr
from langgraph.graph import END, START, StateGraph

from src.agents import analyzer_agent, fixer_agent, make_tester_agent
from src.state import RepairState
from src.workflow import BUG_DESCRIPTION as DEFAULT_BUG_DESCRIPTION
from src.workflow import MAX_ATTEMPTS

CALCULATOR_DIR = Path("examples/buggy_calculator")
CALCULATOR_SOURCE = CALCULATOR_DIR / "calculator.py"
CALCULATOR_TEST = CALCULATOR_DIR / "test_calculator.py"
TEST_FILENAME = "test_calculator.py"

WORK_DIR = Path("results/demo_work")

DEFAULT_BUGGY_CODE = CALCULATOR_SOURCE.read_text(encoding="utf-8")


def _after_tester(state: RepairState) -> str:
    if state["tests_passed"]:
        return "end"
    if state["attempts"] < MAX_ATTEMPTS:
        return "retry"
    return "end"


def _build_graph(tester_agent):
    graph = StateGraph(RepairState)

    graph.add_node("analyzer", analyzer_agent)
    graph.add_node("fixer", fixer_agent)
    graph.add_node("tester", tester_agent)

    graph.add_edge(START, "analyzer")
    graph.add_edge("analyzer", "fixer")
    graph.add_edge("fixer", "tester")
    graph.add_conditional_edges(
        "tester", _after_tester, {"retry": "analyzer", "end": END}
    )

    return graph.compile()


def _prepare_work_dir() -> tuple[Path, Path]:
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)

    source_file = WORK_DIR / "calculator.py"
    shutil.copy2(CALCULATOR_TEST, WORK_DIR / TEST_FILENAME)

    return WORK_DIR, source_file


def run_repair(bug_description: str, buggy_code: str):
    """Run the Analyzer -> Fixer -> Tester loop on a temporary copy of the
    calculator source. The original example files are never touched."""
    work_dir, source_file = _prepare_work_dir()
    source_file.write_text(buggy_code, encoding="utf-8")

    tester_agent = make_tester_agent(TEST_FILENAME, cwd=str(work_dir))

    initial_state: RepairState = {
        "bug_description": bug_description,
        "file_path": str(source_file),
        "code": buggy_code,
        "analysis": "",
        "proposed_code": "",
        "test_output": "",
        "tests_passed": False,
        "attempts": 0,
    }

    # Run pytest on the submitted code before involving the LLM at all.
    initial_state.update(tester_agent(initial_state))

    if initial_state["tests_passed"]:
        return (
            "",
            buggy_code,
            initial_state["test_output"],
            "ALREADY PASSES TESTS",
            0,
        )

    graph = _build_graph(tester_agent)
    final_state = graph.invoke(initial_state)

    status = "REPAIR SUCCESSFUL" if final_state["tests_passed"] else "REPAIR FAILED"
    final_code = final_state["proposed_code"] or final_state["code"]

    return (
        final_state["analysis"],
        final_code,
        final_state["test_output"],
        status,
        final_state["attempts"],
    )


def build_interface() -> gr.Blocks:
    with gr.Blocks(title="Agentic Code Repair Demo") as demo:
        gr.Markdown("## Agentic Code Repair — Calculator Demo")
        gr.Markdown(
            "Analyzer → Fixer → Tester repair loop (max "
            f"{MAX_ATTEMPTS} attempts) running against a temporary copy of "
            "the buggy calculator example. The original example files are "
            "never modified."
        )

        bug_description = gr.Textbox(
            label="Bug description",
            value=DEFAULT_BUG_DESCRIPTION,
            lines=3,
        )
        buggy_code = gr.Code(
            label="Buggy Python code",
            value=DEFAULT_BUGGY_CODE,
            language="python",
        )

        run_button = gr.Button("Repair Code", variant="primary")

        analyzer_output = gr.Textbox(label="Analyzer diagnosis", lines=6)
        fixed_code_output = gr.Code(label="Final repaired code", language="python")
        pytest_output = gr.Textbox(label="Pytest output", lines=8)

        with gr.Row():
            status_output = gr.Textbox(label="Final status")
            attempts_output = gr.Number(label="Repair attempts", precision=0)

        run_button.click(
            fn=run_repair,
            inputs=[bug_description, buggy_code],
            outputs=[
                analyzer_output,
                fixed_code_output,
                pytest_output,
                status_output,
                attempts_output,
            ],
        )

    return demo


def main():
    demo = build_interface()
    demo.launch()


if __name__ == "__main__":
    main()
