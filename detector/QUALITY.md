# Assessing detector code quality

Use separate measurements for control flow, dependencies, types, and test coverage. None establishes readability or maintainability on its own. In particular, a low average complexity can hide one difficult integration, and a passing coverage percentage says nothing about the strength of the assertions.

## Checks and reports

The development dependency group includes Ruff, ty, Radon, Coverage.py, Import Linter, Grimp and mutmut. Install the locked versions with `uv sync --locked --extra default` from `detector/`. Mutation execution needs POSIX fork support; Windows installations omit mutmut and can use WSL for that check. These tools are not runtime dependencies.

| Concern | Check | Policy |
| --- | --- | --- |
| Common mistakes, imports, formatting | Ruff lint and format | Required in CI |
| Function branching | Ruff `PLR0912` | At most 12 branches; required in CI |
| Function size | Ruff `PLR0915` | At most 50 statements; required in CI |
| Cyclomatic complexity | Ruff `C901` | At most 10; required in CI |
| Type consistency | ty | Required in CI |
| Dependency direction and cycles | `.importlinter` and `tests/test_architecture.py` | Required in CI; complete source discovery, declarative layer/forbidden-import/adapter-independence contracts, core dependency allowlists and internal cycle checks |
| Import side effects | `tests/support/import_safety.py` and its positive/negative tests | Required in CI; guards inside isolated children detect selected I/O, process, thread and logging effects |
| Detailed complexity analysis | Radon | Advisory reports; investigate hotspots before changing structure |
| Changes, nesting and coupling | `tools/quality_report.py` using Radon/Grimp/Git | Advisory JSON and Markdown reports in CI, compared with an explicit revision |
| Executed lines and branch outcomes | Coverage.py with pytest | Reported in CI; no arbitrary percentage gate |
| Test sensitivity | Targeted mutmut run | Ubuntu CI; survivors and missing tests reported for review, failed/incomplete runs fail the job |
| Unsupervised thread failures | Pytest thread-exception warnings | Treated as errors in the shared pytest configuration |

Ruff's complexity, branch, and statement limits pass across source and tests without suppressions. The two initial `C901` violations were resolved by separating ONNX provider/session setup and video preparation/encoding. Complexity is now part of the normal blocking lint check.

Ruff also enforces the existing absolute-import convention through `TID252`; import syntax no longer needs a custom AST check. The development report tool is included in lint, formatting and type checks.

[Cyclomatic complexity](https://radon.readthedocs.io/en/stable/intro.html#cyclomatic-complexity) estimates independent control-flow paths. Ruff's branch rule counts branching syntax; it is not the same measurement. Radon also accounts for Boolean operators and comprehensions, so its scores differ from Ruff's. Compare a function against its previous score from the same tool and version.

Parameter count and return count are not gates. Several keyword options and clear early returns are reasonable here. Turning them into configuration objects or deeply nested conditionals just to silence a rule would hurt readability.

## Reproduce the reports

The normal checks are listed in [README.md](README.md#development-checks). For complexity:

```sh
uv run --no-sync ruff check src/aidetector --select C901
uv run --no-sync radon cc --show-complexity --show-closures --min B src/aidetector
```

The first command checks the same complexity limit enforced by normal linting. Radon's `--min B` hides trivial blocks from the text report; `--show-closures` includes nested functions. The JSON artifact includes all ranks.

For coverage and saved reports:

```sh
uv run --no-sync coverage erase
uv run --no-sync coverage run -m pytest
uv run --no-sync coverage combine
uv run --no-sync coverage report
uv run --no-sync coverage html
uv run --no-sync coverage json -o .reports/coverage.json
uv run --no-sync coverage xml
uv run --no-sync radon cc --show-closures --json --output-file .reports/complexity.json src/aidetector
```

Open `.reports/coverage/index.html` and inspect highlighted missing lines and branch destinations. Erasing first prevents stale local runs from inflating the result. Configuration enables [child-process measurement](https://coverage.readthedocs.io/en/latest/subprocess.html), so CLI tests count too. Each process writes its own data; `coverage combine` merges it before reporting. `.coverage*` and `.reports/` are ignored by Git.

The GitHub Actions matrix reports coverage on every test platform. The Ubuntu/Python 3.12 job publishes the `detector-quality` artifact with HTML, JSON, and XML coverage reports, Radon JSON, and the change report below. Reports from different platforms are not merged; hardware and platform differences can change the executed branches.

## Review a change

From `detector/` in a Git checkout:

```sh
uv run --no-sync lint-imports --no-cache
uv run --no-sync python tools/quality_report.py --base HEAD --output .reports/quality
```

Open `.reports/quality.md` for the bounded summary and `.reports/quality.json` for all entries. `HEAD` compares committed source with the current working tree, including untracked Python files. Supply another revision to compare a branch or larger change. An invalid explicit revision fails; `--base empty` deliberately reports everything as new.

The report contains:

- Per-function Radon complexity and maximum control-block nesting, with deltas for existing qualified names. Flat `elif` chains stay at the same nesting depth. This is an advisory nesting measure, not Sonar's cognitive-complexity algorithm. Overload declarations share the implementation's entry, so there are currently 145 callable entries versus 147 AST definitions.
- Module fan-in (direct internal importers), fan-out (direct internal imports), and added/removed dependency edges. Bootstrap having many dependencies and domain records having many consumers are expected; there is no universal coupling limit.
- Added, removed, modified and Git-detected renamed modules. New/removed callables have no numeric complexity delta; unmatched names are not silently compared with zero.
- Exact-path committed touches across the last 100 non-merge commits affecting Python source. Uncommitted edits do not count, and history does not follow renames. A new module's zero touches do not mean it is low risk.

Grimp supplies dependency discovery without executing application imports. The tool uses temporary snapshots; it adds empty package initializers only there when needed to inspect legacy namespace directories, and does not count those files as source. Report graphs exclude type-checking-only imports and arbitrary dynamic imports; the architecture-enforcement graphs deliberately include type-checking imports. No composite cleanliness/risk score is calculated.

CI compares pull requests with their base SHA and pushes with their previous SHA. A new branch or manual run uses the first parent when there is no previous SHA; an initial commit uses the explicit empty baseline. Full history is fetched, and unavailable explicit baselines fail visibly. The summary appears on the workflow run without posting a PR comment. Reports are retained for 14 days; compare the same metric/tool version across runs when reviewing trends.

## Architectural fitness

The detector uses a small hexagonal arrangement: `application` contains use cases and outgoing ports, `domain` owns deterministic rules/state, adapters implement I/O and bootstrap supplies implementations. The [.importlinter](.importlinter) contracts declare all source layers, reject reverse dependencies and keep sources, inference and exporters independent. Shared media/HTTP dependencies remain allowed; direct, deferred, annotation-only and indirect violations are exercised by negative tests. Additional tests preserve the stricter core allowlists and check cycles involving package initializers. Tests with deliberately broken temporary source copies prove that the contracts reject actual violations.

The architecture suite also compares every source Python file with the graph's internal modules. Grimp can omit a subdirectory without `__init__.py`; dependency contracts alone cannot inspect an omitted module. A copied-source regression verifies that the completeness guard catches that omission and that adding the initializer exposes the forbidden dependency. Run `pytest tests/test_architecture.py` for both discovery and dependency checks; `lint-imports` alone only checks the discovered graph.

Safe-import probes install guards in the child process, allow interpreter code/package metadata reads, and reject observed configuration reads, filesystem writes/mutations, sockets, process creation, thread starts and logging configuration. Negative cases test both uncaught and swallowed violations. The probes use `-S -B` and explicit package paths to exclude site/coverage hooks instead of allowing instrumentation writes. These children are intentionally uninstrumented; ordinary behavior tests still measure production coverage. The probe is not a security sandbox for native or hostile code, and the import graph is not a complete model of runtime behavior.

Structural conformance must be paired with change-scenario review. A walkthrough of current callers, ports and construction found these expected edit boundaries:

| Scenario | Expected edits | Evidence/boundary |
| --- | --- | --- |
| Add a delivery destination | Adapter, exporter configuration, bootstrap wiring, schema/docs and tests | `EventDelivery` calls `EventExporter.export`; domain acceptance rules do not depend on a concrete destination |
| Change an event-window rule | Domain policy/assembler and tests; configuration and bootstrap if a new setting is exposed | `DetectionPipeline` supplies observations/time and consumes completed events; storage and HTTP adapters do not own timing rules |
| Replace the inference integration | New adapter, model configuration and bootstrap wiring, adapter/contract tests | `ObjectDetector.detect` returns domain observations; event assembly and delivery consume that existing contract |

This is a source walkthrough, not a claim that those new features have been implemented. For each real feature, compare actual changed files with the expected boundary and explain unexpected cross-layer edits or duplicated policy. A class count or passing import rule cannot establish that responsibilities are well chosen.

## Mutation testing

```sh
uv run --no-sync mutmut run --max-children 4
uv run --no-sync mutmut results
uv run --no-sync mutmut export-cicd-stats
```

Configuration targets `domain/events.py`, `domain/policy.py` and `domain/models.py`, using the domain and delivery tests. mutmut builds disposable working copies in `mutants/`; no mutation needs to be applied to live source. Native statistics are written to `mutants/mutmut-cicd-stats.json`.

The first run produced 135 mutations: 117 killed, five survivors and 13 without a selected test. Nine focused cases added assertions for overlapping batches, source-specific completion, fractional timeouts, default/unscored cooldown and enclosing geometry. The verified run before the navigation cleanup killed all **135 generated mutations**, with no survivors, missing tests or incomplete outcomes. No production changes, mutation exclusions or score-driven rewrites were needed. The grouping cleanup preserves those test bodies. Selection now includes `tests/domain/test_events.py`, `test_policy.py`, `test_models.py` and `tests/application/test_delivery.py`; no additional mutation run was performed for these moves.

This is evidence that the selected tests detect these generated faults. mutmut 3.8 skips decorated properties and does not mutate every declaration, so the result is not complete domain coverage or proof of correctness. Equivalent or intentionally irrelevant survivors need review; do not add tests that merely mirror implementation to chase a percentage.

The separate Ubuntu CI job bounds execution to two children and 15 minutes. It publishes native JSON and survivor listings as `detector-mutations` and in the workflow summary. `mutmut run` returns success even with survivors: CI explicitly verifies a nonempty, complete run and rejects crashes, timeouts, interruptions or skipped/inconsistent outcomes. Survivor/missing-test counts remain advisory and visible for review.

## Recorded measurements — 2026-09-22

These numbers describe the dated baseline below. Run the commands above or read the latest CI artifacts to measure the current checkout; the table is not a continuously updated score.

Measured after the contributor clarity pass on macOS with Python 3.12 on 2026-09-22, using Ruff 0.15.20, Radon 6.0.1, and Coverage.py 7.16.1. All 397 tests passed. The 19 added cases cover architecture discovery, HTTP/Telegram outcomes, complete archives and detector-specific CLI diagnostics. The earlier architecture-boundary cleanup also passed on Python 3.10 and 3.11; their full suites were not rerun for this pass. [REVIEW.md](../docs/history/detector/REVIEW.md) records the responsibility and code-placement decisions. Measurements cover `src/aidetector`, not third-party libraries or development tooling/test code.

| Scope | Line coverage | Branch coverage | Highest Radon complexity |
| --- | --- | --- | --- |
| Entire package | 95.8% (1679/1752) | 88.0% (366/416) | 16 |
| Domain | 100.0% (184/184) | 100.0% (50/50) | 7 |
| Application | 100.0% (103/103) | 100.0% (20/20) | 10 |
| Adapters | 96.3% (944/980) | 86.5% (218/252) | 13 |

Coverage.py's headline result is **94.3%**, which combines statements and branch destinations. It is not the branch-only percentage. [Branch coverage](https://coverage.readthedocs.io/en/7.14.1/branch.html) distinguishes whether alternatives were executed even when their shared source lines were visited. Full coverage of the small domain/application layers means their measured lines and alternatives ran; it is not proof of correctness for every possible input.

The highest Ruff branch count is 9, below the configured limit of 12. The remaining Radon scores above 10 are:

| Function | Radon score | Review focus |
| --- | --- | --- |
| [`main`](src/aidetector/cli.py) | 16 (C) | Several CLI actions and exit paths, including parent-controlled stopping; early returns are appropriate |
| [`_video_frames`](src/aidetector/adapters/media/video.py) | 13 (C) | Crop bounds, overlay carry-forward, and frame transformation; geometry is shared through `BoundingBox.enclosing` |
| [`_cuda_libraries`](src/aidetector/adapters/inference/onnx.py) | 11 (C) | Platform-specific DLL discovery and resource lifetime |
| [`run_detectors`](src/aidetector/runtime.py) | 11 (C) | Detector and health supervision, parent stop requests and orderly draining |

The contributor clarity pass starts from the previously verified adapter grouping. Its structural measurements are:

| Source measure | Before | After |
| --- | --- | --- |
| Python modules | 36 | 36 |
| Physical lines, including blanks and comments | 3120 | 3149 |
| Class definitions | 67 | 67 |
| Functions, methods and closures | 147 | 147 |
| Highest Radon score | 16 | 16 |
| Functions above Radon 10 | 4 | 4 |

Counts come from Python AST definitions. When using Radon's records instead, deduplicate by file and line: closures can appear under both simple and qualified names. Classes include data/configuration records, protocols and exceptions, so fewer classes alone would not establish a better design.

No production module, class or callable was added. The extra lines chiefly document image/event/clock contracts and the scoped diagnostic thread names. Bootstrap helpers receive only their relevant settings. Both public schema files are byte-identical to the previous pass. All existing reference-flow test bodies and assertions were preserved while source-only and disk-only cases moved beside their adapters.

Tests follow production responsibilities; subprocess/model/media helpers live under `tests/support`. Mutation selectors include event, policy and model tests. Ruff, formatting, ty, all five architecture contracts, graph completeness, schema checks and the full behavioral suite pass. The VS Code task commands use the same tools, and the reference flow passes under the installed debugger. No complexity threshold or coverage exclusion changed; earlier measurements and packaging checks remain in [AUDIT.md](../docs/history/detector/AUDIT.md).

The previous grouping pass's installed wheel passed both generated ONNX and Torch smoke variants on Python 3.11, exercising local model downloads, inference, VLM verification, JPEG/MP4 archives, HTTP delivery, health and EOF shutdown. This pass's source suite exercises those adapter contracts, the local reference flow and real CLI diagnostics. Native executables and target hardware were not rebuilt or rerun.

The remaining higher-scoring functions were reviewed and retained: CLI dispatch reads clearly with early exits, frame rendering coordinates crop/overlay decisions, DLL discovery is one platform operation, and supervision keeps failures and cleanup together. Revisit their structure when behavior grows. Extract a function only when it names a useful operation; moving branches into one-use forwarding helpers does not reduce the conceptual work.

Local tests exercise Windows ML registration, device options, and cleanup through a fake SDK. That verifies the adapter contract, not native Windows/GPU execution. Missing hardware paths remain visible for verification on the relevant platforms. The schema entrypoint is also mostly unmeasured because the dedicated `generate-schema --check` command runs outside the pytest coverage session; its schema contract tests still run under pytest.

## Human review still decides cleanliness

For a changed function, review whether its name and inputs explain its purpose, whether state and resource ownership are obvious, whether failure semantics remain explicit, and whether the reader must jump across files to understand a simple operation. Tests should describe outcomes and important alternatives, including failure paths, rather than reproduce implementation details.

For an architectural change, verify that domain rules remain independent of integration frameworks and that each new port or abstraction serves an actual boundary. Import Linter and the architecture tests check explicit imports, including `from package import module`, imports inside functions and type-checking-only imports. The sole external core annotation allowance is NumPy in `domain.models`; isolated domain import probes still require no third-party runtime packages. Negative cases reject annotation-only adapter, configuration, framework and cycle dependencies. External packages are leaves in this graph, not an analysis of their internals. Keep architectural suitability and runtime contracts under review even when the static rules pass.

Radon's maintainability index is available with `uv run --no-sync radon mi --show src/aidetector`, but is not a gate. The initial scan gave every file its broad A grade, including the integration hotspots. Radon describes the index as experimental; its formula includes comments and size, so changing comments or splitting files can improve the number without improving the design.

Review the highest scores and coverage gaps with each relevant change. Do not add blanket exclusions, weaken tests, scatter code across tiny helpers, or raise limits merely to make a report green. Keep behavioral correctness and a clear model of the application ahead of the metrics.
