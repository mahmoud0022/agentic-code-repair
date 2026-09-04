# Agentic Code Repair

## 1. Overview

This project is an agentic AI system that automatically analyzes buggy Python code, proposes a repair, runs pytest to verify the repair, and retries when necessary.

Technology used:

- Python
- LangGraph
- LangChain / ChatOllama
- Qwen2.5-Coder:1.5B
- pytest
- Gradio

The model (Qwen2.5-Coder:1.5B) runs locally through Ollama — no external API calls are made.

## 2. Why this project?

Fixing code is not just about generating code. A useful repair system must:

- understand the failure
- generate a repair
- test it
- use test failures as feedback
- retry if necessary

This project demonstrates that agentic loop — Analyzer, Fixer, and Tester working together with feedback — rather than a single one-shot LLM call.

## 3. System Flow

```
Buggy Code + Bug Description
        ↓
Initial pytest
        ↓
Analyzer
        ↓
Fixer
        ↓
Tester
        ↓
   Tests pass?
    /       \
  Yes       No
   ↓         ↓
  END   Analyzer again
             ↓
           Fixer
             ↓
           Tester
```

Maximum repair attempts = 3.

### Analyzer

Reads:
- bug description
- current source code
- latest pytest output

Finds the likely root cause and suggests the smallest required change.

### Fixer

Uses:
- current code
- Analyzer diagnosis
- latest pytest output

Generates a corrected, complete Python file.

### Tester

Runs pytest on the repaired code and returns:
- pass/fail
- pytest output

If tests fail, the latest failure goes back to the Analyzer.

## 4. Repair Safety

Raw LLM output should not be trusted automatically, so several safeguards were added:

- repairs are made on temporary copies during benchmark/demo execution
- tests cannot be modified by the agent
- benchmark originals are not modified
- correct QuixBugs solutions are never shown to the model
- no arbitrary LLM-generated shell commands are executed
- pytest has a 10-second timeout
- maximum repair attempts = 3

Fixer output validation:

1. Markdown fences are cleaned.
2. JSON output such as `{"corrected_code": "..."}` can be extracted.
3. `ast.parse()` checks that the generated code is valid Python syntax.
4. The repaired file must still contain the original function names.
5. If validation fails, the previous file is kept instead of overwriting it.

This matters because it prevents malformed model output — such as a stray `obj['corrected_code']` — from replacing the real source file.

## 5. Agent Verification

Before trusting benchmark results, the three agents were tested independently in `tests/test_agents.py` using mocked LLM responses.

| Test | Result |
| --- | --- |
| Analyzer receives bug description, code and pytest output | Passed |
| Fixer accepts valid Python code | Passed |
| Fixer extracts JSON-wrapped code | Passed |
| Fixer rejects invalid Python syntax | Passed |
| Fixer rejects code missing the original function | Passed |
| Tester detects passing tests | Passed |
| Tester detects failing tests | Passed |

7/7 tests passed in about 1.54 seconds.

These tests used mocked LLM responses, so they verified the agent implementation independently of Qwen's actual repair ability. This was important because it showed that later repair failures were not simply caused by broken Analyzer/Fixer/Tester wiring.

## 6. QuixBugs Evaluation

QuixBugs was used as a source of real buggy Python programs and pytest test cases.

The system:
1. copies one buggy program to a temporary directory
2. runs its tests
3. asks the agents to repair it
4. runs tests after each repair
5. stops after success or 3 attempts

Only one benchmark task is run at a time for safety.

| Task | Observed result |
| --- | --- |
| GCD | Repaired successfully, 1 attempt |
| BITCOUNT | Repaired successfully, 2 attempts |
| IS_VALID_PARENTHESIZATION | Repaired successfully, 1 attempt |
| TO_BASE | Repair failed |
| SIEVE | Repair failed |
| PASCAL | Repair failed |
| POSSIBLE_CHANGE | Repair failed in an earlier workflow version |
| FIND_FIRST_IN_SORTED | Interrupted / not counted |

We do not report a single official benchmark success rate, because the workflow and safeguards were improved during development — not every task above was evaluated under exactly the same final configuration.

- Successful cases demonstrate that the repair loop works end to end.
- Failed cases reveal the limits of the small local 1.5B model.
- Benchmark failures are also useful results, not something to hide.

## 7. Improvements Made During Development

1. **Initial workflow:** Analyzer → Fixer → Tester → Fixer on failure.
   Problem: a wrong first Analyzer diagnosis could keep influencing every retry.

2. **Improved workflow:** Tester failure → Analyzer again → Fixer → Tester.
   Now each retry uses the newest pytest error.

3. **Fixer validation was added** after discovering that raw LLM responses could corrupt the temporary source file.

4. **Analyzer/Fixer prompts were improved** to:
   - focus on the exact pytest failure
   - make the smallest possible repair
   - preserve function signatures
   - use expected vs. actual test values
   - use the latest feedback on retries

## 8. Gradio Demo

The project includes a small Gradio interface.

User provides:
- bug description
- Python code

The interface shows:
- Analyzer diagnosis
- final repaired code
- pytest output
- repair status
- number of attempts

The bundled calculator example starts with:

```python
def calculate_discount(price, percent):
    return price - (percent / 100)
```

and the system successfully repairs it to:

```python
def calculate_discount(price, percent):
    return price * (1 - percent / 100)
```

with 3 pytest tests passed.

The demo always works on a temporary copy and never overwrites the bundled example.

If the submitted code already passes the tests:
- Analyzer and Fixer are skipped
- status becomes `ALREADY PASSES TESTS`
- attempts = 0

## 9. Running the Project

Create/activate a virtual environment, then install dependencies from `requirements.txt` if available.

Ensure Ollama is running and the model exists:

```
qwen2.5-coder:1.5b
```

Run the Gradio demo:

```
python -m src.demo
```

Run agent tests:

```
pytest tests/test_agents.py -v
```

Run one QuixBugs task:

```
python -m src.evaluate_quixbugs GCD
```

The local benchmark dataset must exist under the expected `benchmark/QuixBugs` directory but is intentionally not committed to Git.

## 10. Current Limitations

- Qwen2.5-Coder 1.5B is lightweight enough to run locally but does not solve every QuixBugs problem.
- A correct agent workflow does not guarantee the LLM will produce the correct repair.
- Function-name validation checks basic structural correctness, not full program semantics.
- The current demo uses the calculator test suite rather than dynamically accepting arbitrary external test suites.
- Evaluation so far is intentionally small and should not be presented as a full QuixBugs benchmark.

## 11. Possible Future Improvements

- use a stronger coding model
- evaluate a larger fixed QuixBugs subset under one unchanged final configuration
- add richer structured LLM output
- improve semantic validation of generated repairs
- add repair history/trace visualization
- support controlled user-provided test suites
- compare different models or prompting strategies

## 12. Project Structure

```
src/
  agents.py
  state.py
  workflow.py
  evaluate_quixbugs.py
  demo.py

tests/
  test_agents.py

examples/
  buggy_calculator/

results/
  generated evaluation outputs
```
