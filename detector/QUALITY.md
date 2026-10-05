# Assessing detector code quality

Control flow, dependencies, types and test coverage are measured separately. None of them establishes readability on its own: a low average complexity can hide one difficult integration, and a coverage percentage says nothing about the strength of the assertions.

## Checks

Install the tools with `uv sync --locked --extra default` from `detector/`. They are development dependencies only. The commands are in the [README](README.md#development-checks).

| Concern | Check | Policy |
| --- | --- | --- |
| Common mistakes, imports, formatting | Ruff lint and format | Required in CI |
| Function shape | Ruff `C901` (complexity ≤ 10), `PLR0912` (≤ 12 branches), `PLR0915` (≤ 50 statements) | Required in CI, without suppressions |
| Types | ty | Required in CI |
| Dependency direction and cycles | [`.importlinter`](.importlinter) and `tests/test_architecture.py` | Required in CI |
| Import side effects | `tests/test_import_safety.py` | Required in CI |
| Unsupervised thread failures | Pytest thread-exception warnings are errors | Required in CI |
| Executed lines and branches | Coverage.py with pytest | Reported; no percentage gate |
| Changes, nesting and coupling | `tools/quality_report.py` (Radon, Grimp, Git) | Advisory report in CI |
| Test sensitivity | mutmut on the domain | Ubuntu CI; survivors reported for review, an incomplete run fails |

Parameter and return counts are deliberately not gated: a few keyword options and clear early returns read better than a configuration object or nested conditionals added to silence a rule. Radon's maintainability index is not used either; its formula rewards comments and smaller files without the design improving.

Ruff counts branching syntax, while Radon also counts Boolean operators and comprehensions, so their scores differ. Compare a function with its own previous score from the same tool.

## Coverage and complexity reports

```sh
uv run --no-sync coverage erase
uv run --no-sync coverage run -m pytest
uv run --no-sync coverage combine
uv run --no-sync coverage report
uv run --no-sync coverage html
uv run --no-sync radon cc --show-complexity --show-closures --min B src/aidetector
```

Erasing first keeps stale runs out of the result. Child processes are measured too, so CLI tests count; each process writes its own data and `coverage combine` merges it. Open `.reports/coverage/index.html` for missing lines and branch destinations. Linux CI collects branch coverage and publishes it with the Radon output as the `detector-quality` artifact; Windows and macOS run the same tests without instrumentation, and their results are not merged.

`tests/integration/` holds the expensive real SDK exports. They run by default and in every CI run. Keep one real check per boundary and cover input variants at the cheapest layer that owns the behavior; do not replace real resource cleanup with mock-only assertions.

## Reviewing a change

```sh
uv run --no-sync lint-imports --no-cache
uv run --no-sync python tools/quality_report.py --base HEAD --output .reports/quality
```

`.reports/quality.md` summarizes and `.reports/quality.json` lists everything, comparing the working tree, including untracked files, with the given revision. Use a branch or commit to review a larger change; `--base empty` reports everything as new. The report shows:

- complexity and nesting per function, with the change for functions that already existed;
- module fan-in, fan-out and added or removed dependency edges. Bootstrap importing much and domain records being imported by many is expected; there is no coupling limit;
- added, removed, modified and renamed modules;
- how often each file was touched in the last 100 commits.

There is no composite score. CI compares a pull request with its base and a push with the previous commit, and shows the summary on the workflow run.

## Does the structure fit?

Passing import rules show that dependencies point the right way, not that responsibilities are well chosen. Check a real change against the edits its kind should need:

| Change | Expected edits |
| --- | --- |
| Add a delivery destination | An adapter, its configuration, bootstrap wiring, schema, docs and tests. No domain change. |
| Change an event-window rule | Domain policy or assembler and their tests; configuration and bootstrap only when a new setting is exposed. |
| Replace the inference integration | A new adapter, model configuration, bootstrap wiring and adapter tests. Event assembly and delivery stay as they are. |

Explain edits that cross a layer unexpectedly or repeat a policy in a second place.

## Mutation testing

```sh
uv run --no-sync mutmut run --max-children 4
uv run --no-sync mutmut results
uv run --no-sync mutmut export-cicd-stats
```

mutmut mutates `domain/events.py`, `domain/policy.py` and `domain/models.py` in disposable copies under `mutants/` and runs the domain and delivery tests against them. It needs POSIX fork, so use WSL on Windows. A killed mutant shows that the selected tests detect that generated fault; it is not proof of correctness, and mutmut skips decorated properties. Review a survivor before acting on it: an equivalent mutant needs no test, and a test that only mirrors the implementation adds nothing.

`mutmut run` succeeds even with survivors. The CI job therefore checks for a complete, nonempty run itself and fails on crashes, timeouts or skipped outcomes; survivor counts stay advisory.

## What the numbers cannot decide

For a changed function, ask whether its name and inputs explain its purpose, whether state and resource ownership are obvious, whether failures stay explicit, and whether a reader must jump between files to follow a simple operation. For an architectural change, ask whether the domain still knows nothing of integrations and whether each new port serves a real boundary.

Do not add exclusions, weaken tests, split code into tiny helpers or raise a limit to make a report green. Extract a function when it names a useful operation.
