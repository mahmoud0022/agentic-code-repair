import ast
import json
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


def _function_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _extract_code(text: str) -> str | None:
    """Return valid Python source from an LLM response, or None if the
    response is malformed (e.g. wrapped in JSON) and not usable code."""
    candidate = _strip_code_fences(text)

    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("corrected_code"), str):
        candidate = parsed["corrected_code"].strip() + "\n"

    try:
        ast.parse(candidate)
    except SyntaxError:
        return None

    return candidate


def analyzer_agent(state: RepairState) -> dict:
    prompt_parts = [
        "You are a precise code diagnosis assistant.",
        f"Bug description: {state['bug_description']}",
        "Current implementation:",
        state["code"],
    ]
    if state.get("test_output"):
        prompt_parts.append("Latest pytest output (exact failing assertion/error):")
        prompt_parts.append(state["test_output"])
    prompt_parts.append(
        "Diagnose the bug. Cover only:\n"
        "1. The exact failing pytest assertion or error (if given).\n"
        "2. What the current implementation actually does.\n"
        "3. The smallest likely root cause.\n"
        "4. The exact code change needed to fix it.\n\n"
        "Do not rewrite the whole program. Do not invent new tests. "
        "Do not discuss unrelated edge cases. Keep the diagnosis short "
        "and specific."
    )
    prompt = "\n\n".join(prompt_parts)

    response = llm.invoke(prompt)
    return {"analysis": response.content}


def fixer_agent(state: RepairState) -> dict:
    expected_functions = _function_names(state["code"])

    prompt_parts = [
        "You are a precise Python code fixer.",
        f"Bug description: {state['bug_description']}",
        f"Analyzer diagnosis: {state['analysis']}",
        "Current source code:",
        state["code"],
    ]
    if state.get("test_output"):
        prompt_parts.append("Latest pytest output:")
        prompt_parts.append(state["test_output"])
    if state["attempts"] > 0:
        prompt_parts.append(
            "Note: the current source code above may already be the "
            "result of a previous failed repair attempt. Do not blindly "
            "repeat that previous fix - use the latest pytest output to "
            "correct this version."
        )
    prompt_parts.append(
        "Fix the bug using the smallest possible change:\n"
        "- Preserve the existing function name(s) and signature(s).\n"
        "- Preserve all unrelated code exactly as-is.\n"
        "- Do not add tests.\n"
        "- Do not add imports unless strictly required for the fix.\n"
        "- Do not add explanations or comments unless already present and "
        "needed.\n"
        "- Do not change any public API.\n"
        "- Pay close attention to the exact expected vs actual values in "
        "the pytest output and fix the logic accordingly.\n\n"
        "Return ONLY the complete corrected Python file contents. "
        "No markdown fences. No explanation."
    )
    prompt = "\n\n".join(prompt_parts)

    response = llm.invoke(prompt)
    fixed_code = _extract_code(response.content)

    if fixed_code is None:
        return {"attempts": state["attempts"] + 1}

    if not expected_functions <= _function_names(fixed_code):
        return {"attempts": state["attempts"] + 1}

    with open(state["file_path"], "w", encoding="utf-8") as f:
        f.write(fixed_code)

    return {
        "proposed_code": fixed_code,
        "code": fixed_code,
        "attempts": state["attempts"] + 1,
    }


def make_tester_agent(test_file_path: str, cwd: str | None = None):
    def tester_agent(state: RepairState) -> dict:
        result = subprocess.run(
            ["python", "-m", "pytest", test_file_path, "-q"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        output = result.stdout + result.stderr
        return {
            "test_output": output,
            "tests_passed": result.returncode == 0,
        }

    return tester_agent


tester_agent = make_tester_agent(TEST_FILE_PATH)
