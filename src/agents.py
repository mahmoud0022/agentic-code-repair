import subprocess

from langchain_ollama import ChatOllama

from src.state import RepairState

TEST_FILE_PATH = "examples/buggy_calculator/test_calculator.py"

llm = ChatOllama(model="qwen2.5-coder:1.5b", temperature=0)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip() + "\n"


def analyzer_agent(state: RepairState) -> dict:
    prompt = (
        "You are a code analysis assistant.\n"
        f"Bug description: {state['bug_description']}\n\n"
        "Current source code:\n"
        f"{state['code']}\n\n"
        "Briefly explain what is probably wrong and what should change. "
        "Do not rewrite the file, just explain."
    )
    response = llm.invoke(prompt)
    return {"analysis": response.content}


def fixer_agent(state: RepairState) -> dict:
    prompt_parts = [
        "You are a Python code fixer.",
        f"Bug description: {state['bug_description']}",
        f"Analysis: {state['analysis']}",
        "Current source code:",
        state["code"],
    ]
    if state.get("test_output"):
        prompt_parts.append("Previous pytest output:")
        prompt_parts.append(state["test_output"])
    prompt_parts.append(
        "Return ONLY the complete corrected Python file contents. "
        "No markdown fences. No explanation."
    )
    prompt = "\n\n".join(prompt_parts)

    response = llm.invoke(prompt)
    fixed_code = _strip_code_fences(response.content)

    with open(state["file_path"], "w", encoding="utf-8") as f:
        f.write(fixed_code)

    return {
        "proposed_code": fixed_code,
        "code": fixed_code,
        "attempts": state["attempts"] + 1,
    }


def tester_agent(state: RepairState) -> dict:
    result = subprocess.run(
        ["python", "-m", "pytest", TEST_FILE_PATH, "-q"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    return {
        "test_output": output,
        "tests_passed": result.returncode == 0,
    }
