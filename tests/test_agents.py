import json
from unittest.mock import MagicMock

from src.agents import analyzer_agent, fixer_agent, make_tester_agent


class FakeResponse:
    def __init__(self, content):
        self.content = content


def mock_llm(monkeypatch, content):
    mock_invoke = MagicMock(return_value=FakeResponse(content))
    fake_llm = MagicMock(invoke=mock_invoke)
    monkeypatch.setattr("src.agents.llm", fake_llm)
    return mock_invoke


def make_state(**overrides):
    state = {
        "bug_description": "The discount calculation is incorrect.",
        "file_path": "",
        "code": "",
        "analysis": "",
        "proposed_code": "",
        "test_output": "",
        "tests_passed": False,
        "attempts": 0,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


def test_analyzer_prompt_contains_expected_context(monkeypatch):
    mock_invoke = mock_llm(monkeypatch, "The bug is in the discount formula.")

    state = make_state(
        bug_description="The discount calculation is incorrect.",
        code="def calculate_discount(price, percent):\n    return price - percent\n",
        test_output="FAILED test_calculator.py::test_discount - assert 80 == 20",
    )

    result = analyzer_agent(state)

    assert mock_invoke.call_count == 1
    prompt = mock_invoke.call_args[0][0]

    assert "The discount calculation is incorrect." in prompt
    assert "def calculate_discount(price, percent):" in prompt
    assert "FAILED test_calculator.py::test_discount" in prompt
    assert result["analysis"] == "The bug is in the discount formula."


# ---------------------------------------------------------------------------
# Fixer
# ---------------------------------------------------------------------------


def test_fixer_writes_valid_code(monkeypatch, tmp_path):
    original_code = "def example(x):\n    return x\n"
    fixed_code = "def example(x):\n    return x + 1\n"
    file_path = tmp_path / "example.py"
    file_path.write_text(original_code, encoding="utf-8")

    mock_llm(monkeypatch, fixed_code)

    state = make_state(file_path=str(file_path), code=original_code, attempts=0)

    result = fixer_agent(state)

    assert file_path.read_text(encoding="utf-8") == fixed_code
    assert result["code"] == fixed_code
    assert result["proposed_code"] == fixed_code
    assert result["attempts"] == 1


def test_fixer_extracts_json_wrapped_code(monkeypatch, tmp_path):
    original_code = "def example(x):\n    return x\n"
    inner_code = "def example(x):\n    return x + 1\n"
    llm_output = json.dumps({"corrected_code": inner_code})
    file_path = tmp_path / "example.py"
    file_path.write_text(original_code, encoding="utf-8")

    mock_llm(monkeypatch, llm_output)

    state = make_state(file_path=str(file_path), code=original_code, attempts=0)

    result = fixer_agent(state)

    assert file_path.read_text(encoding="utf-8") == inner_code
    assert result["code"] == inner_code
    assert result["proposed_code"] == inner_code
    assert result["attempts"] == 1


def test_fixer_rejects_invalid_syntax(monkeypatch, tmp_path):
    original_code = "def example(x):\n    return x\n"
    file_path = tmp_path / "example.py"
    file_path.write_text(original_code, encoding="utf-8")

    mock_llm(monkeypatch, "def example(x:\n    return x +")

    state = make_state(file_path=str(file_path), code=original_code, attempts=0)

    result = fixer_agent(state)

    assert file_path.read_text(encoding="utf-8") == original_code
    assert "code" not in result
    assert "proposed_code" not in result
    assert result["attempts"] == 1


def test_fixer_rejects_syntactically_valid_garbage_missing_function(
    monkeypatch, tmp_path
):
    original_code = "def example(x):\n    return x\n"
    file_path = tmp_path / "example.py"
    file_path.write_text(original_code, encoding="utf-8")

    mock_llm(monkeypatch, "obj['corrected_code']")

    state = make_state(file_path=str(file_path), code=original_code, attempts=0)

    result = fixer_agent(state)

    assert file_path.read_text(encoding="utf-8") == original_code
    assert "code" not in result
    assert "proposed_code" not in result
    assert result["attempts"] == 1


# ---------------------------------------------------------------------------
# Tester
# ---------------------------------------------------------------------------


def _write_module_and_test(tmp_path, func_body):
    (tmp_path / "sample.py").write_text(
        f"def add_one(x):\n{func_body}\n", encoding="utf-8"
    )
    test_path = tmp_path / "test_sample.py"
    test_path.write_text(
        "from sample import add_one\n\n\n"
        "def test_add_one():\n    assert add_one(1) == 2\n",
        encoding="utf-8",
    )
    return test_path.name


def test_tester_reports_passing(tmp_path):
    test_name = _write_module_and_test(tmp_path, "    return x + 1")
    tester_agent = make_tester_agent(test_name, cwd=str(tmp_path))

    result = tester_agent(make_state())

    assert result["tests_passed"] is True
    assert "passed" in result["test_output"]


def test_tester_reports_failing(tmp_path):
    test_name = _write_module_and_test(tmp_path, "    return x")
    tester_agent = make_tester_agent(test_name, cwd=str(tmp_path))

    result = tester_agent(make_state())

    assert result["tests_passed"] is False
    assert "failed" in result["test_output"].lower()
