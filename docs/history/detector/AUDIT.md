# Detector rewrite audit

Historical assessment: source paths, measurements and recommendations describe the recorded snapshot. Start with the [current contributor guide](../../../CONTRIBUTING.md) for the maintained implementation.

Baseline commit: `bcd98db85823c5f474d75a3fbe926df961be0782`.

Scope was narrowed by the user to Python on 2026-09-18. The broader task goal is interpreted with this explicit restriction. Web source changes are excluded; shared detector-generated JSON schemas remain in scope.

## Baseline verification

- Existing suite: 21 tests passed in 23.26 seconds on Python 3.12/macOS.
- Ruff: passed.
- `ty check src/aidetector`: nine diagnostics (constructor unions, an unsafe pathlib assignment, ONNX optional values/dynamic module attributes, and platform-only WinML imports).
- No live cameras, external AI providers, Telegram bots, or webhooks were used.

## Findings and required outcomes

| Area | Evidence in baseline | Required outcome |
| --- | --- | --- |
| Import side effects | `utils/config.py` loads config at module import; absent config triggers HTTP/template writing | Explicit read-only config loading; safe imports and offline schema generation |
| Domain coupling | Detection/image types, HTTP config, confidence rules, hardware defaulting, and path formatting share `utils/config.py` | Domain data/rules independent of configuration and integrations |
| Orchestration | Detector builds adapters and runs frame, timeout, and export logic over shared dictionaries | Explicit composition and single ownership of event state |
| Concurrency | Timeout and frame threads mutate the same detections; export worker changes cooldown | Serialize state changes; bounded, ordered delivery |
| Lost errors | Submitted export futures are never observed; exporter and media exceptions become logs/None | Observable failures with explicit recovery boundaries |
| Shutdown | Manager only stops health; timeout loop and stream condition can outlive shutdown; health sleeps are not interruptible | Stop all sources/workers, wake waiters, drain eligible events, release resources |
| EOF | In-progress detections are not explicitly flushed | Flush qualifying events on EOF and user shutdown |
| Source classification | First source decides loading mode for every source | Validate compatible source groups or handle each group explicitly |
| Time | Finite files use processing wall time | Group finite input according to media timestamps |
| Retention | Collector trims before appending, retaining one extra frame | Enforce the configured bound after every append |
| Validation | Exhausted provider attempts implicitly return None, also used for optional validation | Distinguish unavailable validation from disabled validation |
| VLM media | IMAGE crop defaults to plotted output; requested crop padding not applied there | Deliberate, tested crop/content construction |
| Disk | Empty confidence causes max() failure; second-resolution folders collide | Support no-YOLO events and never overwrite an existing event |
| Metadata | Generator imports `openai.types.Metadata`; committed schema describes a string map | Generate schema from actual event metadata |
| Webhook | Duplicate encoding branches; broad catch hides failed delivery; default timeout unbounded | Shared rendering, finite request timeout, observable transport errors |
| Telegram | Inherits webhook transport; may index an empty media list; video encoded twice | Compose transport/media; handle message, single media, and album cases |
| FFmpeg | Broad catch; zero duration can divide by zero; raw stdin writes with piped stderr risk blocking | Managed process, explicit failures, deterministic FPS and cleanup |
| ONNX | Global state and monkeypatches hide configuration lifetime; setup catches everything | Explicit startup ownership and narrowly documented integration workarounds |
| WinML | Singleton uses destructor cleanup and deletes installed package DLL | Explicit lifetime; review/remove destructive runtime workaround |
| Dependencies | Runtime imports rely on transitive requests/NumPy/OpenCV; Docker references absent nvidia extra | Declare direct dependencies and align distributable build commands |
| Tests | Constructors bypassed with __new__; global chdir/config setup needed for collection | Public constructors, isolated fixtures, behavior-focused tests |
| Documentation | README lists unsupported strategy and inaccurate frame/default semantics | Document implemented behavior and intentional migration changes |

## Execution checkpoints

- [x] Read Python implementation, tests, packaging, and shared formats; run baseline checks.
- [x] Record design, behavioral contracts, and engineering rules.
- [x] Implement independent domain, validated configuration, and event pipeline.
- [x] Verify complete local video-to-disk reference flow.
- [x] Replace source, YOLO, VLM, media, export, and health integrations.
- [x] Replace startup, supervision, platform setup, and distribution entrypoints.
- [x] Remove legacy modules and test scaffolding.
- [x] Verify schemas, full tests, static checks, builds, performance, and migration instructions.

## Verification results — 2026-09-18

Local platform: macOS arm64. All checks below use temporary outputs. No live configuration, detection archive, recording, or model weight was rewritten.

| Check | Result |
| --- | --- |
| Python 3.10.18, locked default extra | 120 tests passed; ONNX Runtime 1.23.2 |
| Python 3.11.13, locked default extra | 120 tests passed; ONNX Runtime 1.27.0 |
| Python 3.12.0, existing project environment synced to lock | 120 tests passed; ONNX Runtime 1.27.0 |
| Ruff, including imports/modern syntax/bugbear rules | Passed |
| Ruff formatting | All 50 Python files formatted |
| ty on application source | Passed, zero diagnostics |
| Generated configuration and metadata schemas | Match committed files; contract tests validate example/template and legacy event records |
| Architecture/import checks | Domain imports without site packages; domain/application imports point inward; config/CLI/schema imports create no files or logging configuration |
| Process lifecycle | Real SIGTERM tests drain eligible events and retain exit status 1 for a delivery failure during shutdown |
| Video reference flow | Real AVI input, JPEG decode, MP4 encode/decode, metadata, trailing frames, per-file EOF, and duplicate-timestamp archives passed |
| Real inference contract | Generated ONNX model passes real Ultralytics batching/tracking for two sources, changing active sources, class mapping, and a single retained ONNX session |
| Existing segmentation model | Local `yolo26m-seg.onnx` processed four frames of the example recording with tracking enabled; one event, four-frame playable MP4, correct metadata, zero delivery/validation failures |
| Python distributions | Wheel and source archive built; installed-wheel import and CLI configuration check passed; archives exclude weights, local data, environments, bytecode, and legacy modules |
| macOS executable | Built with Python 3.11 and PyInstaller; passed two-source ONNX tracking, structured verification through a local fake API, JPEG/MP4 archive creation, local HTTP delivery, and EOF shutdown |
| Repository hygiene | `git diff --check` passed; no web source changes; no runtime imports of legacy modules |

The baseline's 21 implementation-coupled tests were replaced with tests of public constructors, domain behavior, external contracts, resources, and actual local I/O. The higher count alone is not the quality criterion: failures now include previously untested behaviors such as validation outages, queue saturation, stalled capture shutdown, incomplete archive publication, signal draining, and packaged inference.

## Same-input inference comparison

Compared the baseline commit and replacement in separate processes with the same Python 3.12 environment, Ultralytics 8.4.80, ONNX Runtime 1.27.0, CPU provider, existing `yolo26m-seg.onnx`, and first ten frames of `example/sprong24.mp4`. Frames were resized to 640×360; settings were `task=segment`, `tracking=true`, `confidence=0.1`, and `imgsz=640`. Startup includes imports, loading those input frames, and model preparation. Steady-state median excludes the first inference.

| Measurement | Baseline | Replacement |
| --- | ---: | ---: |
| Startup | 1.541 s | 1.465 s |
| First inference | 0.204 s | 0.200 s |
| Median subsequent inference | 0.192 s | 0.188 s |
| Ten inferences total | 1.941 s | 1.902 s |
| Process peak RSS | 847.8 MiB | 782.6 MiB |

Input SHA-256: `fdf97101f3cdf19f47206c8a2a9b5f2c14548cbdc2291a48cefef3cfea11cd40`. Model SHA-256: `41dd1f4cf02b1a1e94b499c072dafa9be771f4373f5f09666da7193d47b5ea6c`. These identify the local artifacts used; the weights are not part of the repository or distributions.

All ten frames had **identical class names, confidence values, and bounding-box coordinates**. This short single-run comparison checks for a material regression; it is not a claim of a general speedup or a long-running memory benchmark. The deterministic tests separately verify queue and capture-buffer bounds.

## Distribution findings resolved during verification

- ONNX Runtime 1.24.x declares Python 3.10 compatibility but provides no CPython 3.10 CPU/GPU wheels. The Python 3.10 dependency markers now select the 1.23.x line; clean installation and the full suite pass. The [published 1.24.1 files](https://pypi.org/project/onnxruntime/1.24.1/#files) and actual installation failure established this mismatch.
- A local frozen build using Python 3.12.0 failed inside Torch's NumPy compatibility import. The Python 3.11 release build passes the full executable smoke test. The workflow now explicitly selects its intended Python 3.11 interpreter. No runtime patch to Torch was added.
- Reading exported-model class names initially caused a second ONNX session to be loaded. The adapter now retains one predictor; a real ONNX test proves this behavior.
- Source-package discovery initially walked unrelated local data. Explicit source-distribution inclusion now produces a small archive containing only code, metadata, the lockfile, and documentation.
- A successful `--version` invocation did not establish packaged inference/provider support. Release jobs now run `python -m tests.smoke_package <executable>` before uploading artifacts.

## Remaining platform validation

- Windows ML SDK registration/device execution, Windows CUDA, and Linux NVIDIA/Jetson acceleration were not executable on this macOS host. Provider selection, setup rollback, DLL-preload invocation, tracking, and ONNX contracts have local coverage; hardware execution still needs the corresponding host.
- Docker entrypoints, dependency extras, and build context were updated and reviewed. The local Docker daemon was not running, so no container build/run was performed.
- GitHub Actions definitions were updated and parsed locally. No remote workflow run, release, deployment, or production switch was triggered.
- Live cameras, real Telegram delivery, production webhooks, and commercial VLM responses were not used. External transport/provider tests use fakes; the executable test uses a real HTTP server bound only to localhost. Detection accuracy and provider-specific video support remain properties of the chosen model/service.

Migration and recovery steps are in [MIGRATION.md](../../../detector/MIGRATION.md); ongoing engineering constraints are in [AGENTS.md](../../../detector/AGENTS.md).

## Targeted assessment fixes — 2026-09-18

| Area | Correction and evidence |
| --- | --- |
| Docker dependencies | Redeclare `TARGETARCH` inside the runtime build stage so the AMD64 branch installs the NVIDIA extra. Reviewed argument scope; the Docker daemon is unavailable, so container execution remains unverified. |
| Buffered event boundaries | Consume observations in timestamp order, retaining eligible trailing frames before expiration. Tests cover multiple batch partitions, refreshed inactivity deadlines, and multiple windows within one batch. |
| Archive categories | Require a single category name in both Python configuration and JSON Schema. Reject nested, absolute, blank, and dot-only names; a real video-to-disk flow checks the web reader's category/stage/timestamp layout for default and explicit categories. |
| Signed ONNX URLs | Classify HTTP models by URL path, preserving CUDA/TensorRT setup for URLs with queries or fragments. Tests verify DLL-preload invocation and explicit-provider validation. |
| Missing FFmpeg | Convert discovery failure into `MediaError` before preparing clip data. Tests verify unavailable validation, reported delivery failure, and continued independent delivery across successive events. |
| Telegram photos | Apply separate 10 MB photo and 12 MB video limits. Real JPEG tests start above the photo limit and verify compliant single-photo and album payloads. |

The new regressions failed before their corresponding fixes. After implementation, **164 tests pass on each of Python 3.10.18, 3.11.13, and 3.12.0**. Ruff, formatting, ty, schema consistency, and `git diff --check` pass. The wheel and source distribution build offline. The freshly installed wheel passes the two-source ONNX/local-VLM/JPEG/MP4/HTTP/EOF smoke test using its packaged CLI. GPU hardware, Docker execution, and real external destinations were not used for these checks.

## Maintainability assessment and rework — 2026-09-18

The subsequent full review is recorded in [REVIEW.md](REVIEW.md), with current measurements and commands in [QUALITY.md](../../../detector/QUALITY.md). The rework clarifies detection data, provider selection, model lifetime, media encoding, delivery reporting, and cache ownership. It preserves the existing event/configuration schemas and fixes the reproduced event-retention, startup-cleanup, crop, and local-filename defects.

| Verification | Result |
| --- | --- |
| Behavioral suite with branch coverage | 179 passed on each of Python 3.10.18, 3.11.13, and 3.12.0 |
| Ruff, formatting and ty | Passed; cyclomatic complexity now enforced at 10 without suppressions |
| JSON schemas and dependency lock | Checks passed; schema files and runtime dependency versions unchanged in this pass |
| Python 3.12 coverage | 93.2% executable lines, 81.5% branch outcomes; Coverage.py combined headline 91.0% |
| Wheel and source distribution | Built offline; wheel source matches all 32 current Python modules; no superseded packages, model weights, recordings, environments or reports in the source archive |
| Installed-wheel smoke test | Passed from a separate Python 3.11 environment, with imports verified to come from the installed wheel |
| macOS frozen executable | Rebuilt with Python 3.11/PyInstaller and passed the full local end-to-end smoke test |
| Dockerfile checks | BuildKit checks passed without warnings for AMD64, ARM64, and JetPack 6 after declaring each base stage's platform explicitly |
| Architecture | Dependency tests passed, including runtime/configuration/adapter boundaries; no cycles found in explicit internal from-imports |

Both package smoke tests ran two-source ONNX tracking, structured VLM verification through a localhost fake service, real JPEG/MP4 archive creation, HTTP delivery, and EOF shutdown. The frozen executable's first launch was blocked by the macOS sandbox at PyInstaller's startup semaphore. The same binary passed outside that sandbox; no application workaround was added.

The Docker daemon became available for this pass. Checks resolved the actual base-image metadata for each release target; they did not build or run the GPU images. Windows ML/GPU API contracts have additional local fake-SDK coverage, while native Windows ML/CUDA/Jetson execution remains unverified on this host. No real camera credentials, AI providers, Telegram bots, or production webhooks were used. The explicit tradeoffs in REVIEW.md remain visible rather than being hidden by exclusions or speculative abstractions.


## Second full scan and focused rework — 2026-09-18

The new goal started from the 179-test implementation. All 32 source modules, tests, input/output contracts, and distribution definitions were reviewed again. The resulting changes centralize source validation, release export-only model weights, apply native inference precision, align JPEG error handling with other media failures, and preserve verifier fallback when a media strategy cannot run. [REVIEW.md](REVIEW.md) records the evidence and architecture decisions; [MIGRATION.md](../../../detector/MIGRATION.md) records behavior corrections.

Before the corresponding fixes, targeted regressions failed for accepted unsupported source configurations, retained export-only models, ignored native FP16 selection, JPEG codec exceptions stopping delivery, and video encoding failure skipping a usable image verifier. Existing tests were updated to use valid source identifiers where they previously used arbitrary placeholders. Assertions on event behavior and archive compatibility were preserved.

| Final verification | Result |
| --- | --- |
| Python 3.10.18 | 207 tests passed with the locked default extra |
| Python 3.11.13 | 207 tests passed with the locked default extra |
| Python 3.12.0 with subprocess/branch coverage | 207 tests passed; 93.7% lines (1594/1702), 82.6% branch outcomes (337/408), 91.5% combined |
| Ruff, formatting, ty, schema consistency and lockfile | Passed; no new dependencies, rule suppressions or coverage exclusions |
| Architecture | Layer checks, safe-import subprocess checks, and the new required internal import-cycle check passed |
| Native Torch setup | Locally generated untrained checkpoints verify actual FP32/FP16 backend parameters without downloading weights |
| Torch-to-ONNX contract | Real export and subsequent inference pass; the export-only model is collected before inference starts |
| Installed wheel | Installed the exact rebuilt wheel into a separate Python 3.11 environment, verified the import location, and passed both ONNX and `.pt` smoke variants |
| macOS executable | Rebuilt from the final source with Python 3.11/PyInstaller; both ONNX and `.pt` smoke variants passed outside the macOS sandbox required by its startup semaphore |
| Package contents | Wheel matches all 32 source modules byte for byte; source archive matches included code/docs and excludes local weights, recordings, environments, reports and runtime data |
| CI definitions | YAML parsed locally. Native release jobs now require both smoke variants; detector tests also trigger on release-workflow edits |
| Repository hygiene | Formatting and `git diff --check` passed; changes remain within the Python detector, its tests/docs and detector workflows |

The package smoke variants exercise two sources, real inference, structured verification through a localhost fake provider, JPEG/MP4 archives, local HTTP delivery, and EOF shutdown. The ONNX variant covers stable tracking; the generated checkpoint variant covers the distribution's model-loading/export path. No real camera, commercial AI endpoint, Telegram bot or production webhook was used.

The real export test reports two upstream Torch exporter deprecation warnings. They remain visible and are not application failures. Native Windows ML/CUDA/Jetson execution and GPU driver compatibility remain unverified on this macOS host. Docker build definitions and dependencies did not change in this pass; the earlier platform checks are recorded above. No remote workflow or release was triggered. Large active clips still have count/duration bounds rather than a byte budget, as explained in REVIEW.md.

## Third full scan: ownership and failure contracts — 2026-09-18

This goal started from the 207-test state. All 32 Python source modules, their tests, schemas and distribution definitions were reviewed again. [REVIEW.md](REVIEW.md) now presents one current assessment with a module-by-module decision table; the chronological evidence from earlier passes remains in this audit.

Five new regression cases failed before the fixes: partial capture startup left its first thread alive, simultaneous capture failures lacked diagnostics, simultaneous detector failures lacked diagnostics, and unexpected SDK `IndexError`/`ValueError` failures were swallowed by verifier fallback. Startup now belongs to the capture cleanup scope, each failed worker reports its exception, and the verifier parser distinguishes malformed answers with `InvalidAnswer`.

The structural cleanup removes the stateless mapper object, two unnecessary confidence helpers, and archive-stage naming from the domain. Resolved classes now drive both SDK filtering and result mapping. The disk adapter owns the legacy stage projection, with real archive tests for approved, rejected, unvalidated and failed outcomes. Added pipeline/runtime tests verify idle-source expiry, independent source completion, shutdown flushing and validation-failure totals.

| Final verification | Result |
| --- | --- |
| Python 3.10.18 | 223 tests passed |
| Python 3.11.13 | 223 tests passed |
| Python 3.12.0 with subprocess/branch coverage | 223 tests passed; 94.3% lines (1602/1699), 84.0% branch outcomes (341/406), 92.3% combined |
| Domain/application coverage | 100% of measured lines and branch outcomes in both layers; this is coverage, not a correctness proof |
| Ruff, formatting and ty | Passed without new suppressions; highest Ruff branch count remains 9 |
| Architecture | Inward dependency, safe-import subprocess and internal import-cycle checks passed |
| Schemas and dependencies | Schema check and offline lock check passed; schema files, dependency definitions and lockfile match this pass's starting state |
| Complexity | Maximum Radon score remains 15. Four functions exceed 10, up from three because archive-stage selection moved into the disk writer (10 to 11). Functions/methods/closures decrease from 149 to 145 when repeated class records are counted only once |
| Wheel and source distribution | Built offline; wheel matches all 32 source modules byte for byte; source archive matches 42 allowed source/documentation/package files and excludes runtime data, recordings, weights, environments and reports |
| Installed wheel | Fresh Python 3.11 environment with runtime/default dependencies only; imports verified from site-packages; ONNX and generated `.pt` smoke variants both passed |
| macOS executable | Fresh Python 3.11/PyInstaller build; both ONNX and generated `.pt` smoke variants passed |
| Final review | Compared this pass's source changes against its saved starting snapshot; checked removed-symbol references, code formatting and repository whitespace |

The exact wheel tested has SHA-256 `4d25d6213bc603e138539e641a8b0aac3bbae805d595af4c1b3b47076c0b7986`. Both installed-wheel and frozen-executable tests exercised two-source inference, structured verification through a localhost fake provider, real JPEG/MP4 archives, HTTP delivery and normal EOF shutdown. The frozen smoke ran outside the macOS sandbox because PyInstaller needs the previously identified startup semaphore; no application workaround or unrelated access was introduced.

An additional advisory Ruff scan for simplification, return, argument, performance and miscellaneous patterns found only intentional SDK/callback parameters and the verifier's per-attempt exception handling. Those rule families were not added as blanket gates. The existing complexity, branch, statement, typing and architecture checks remain appropriate.

The two upstream Torch export deprecation warnings remain visible. Native Windows ML/CUDA/Jetson execution, GPU images, real cameras and real notification/provider endpoints were not exercised. Docker and release workflow definitions are unchanged in this pass. Active footage still lacks a byte budget, and the SDK integration still assumes one application setup per process. These tradeoffs are recorded explicitly in REVIEW.md.

## Principles review: shared supervision and input boundaries — 2026-09-18

This goal started from the 223-test state. The review challenged the existing design against dependency direction, responsibility and resource ownership, interface scope, invariants, failure semantics and behavioral evidence. [REVIEW.md](REVIEW.md) maps these criteria to the implementation. The completion criterion is a defensible engineering assessment with no unresolved actionable finding from this review, not an assertion of Robert Martin's personal approval.

Two concrete gaps were reproduced before correction. Health monitoring owned a separate thread, saved exception and bootstrap callback; when one source could not close, that callback could skip stopping another source and raise an unhandled thread exception. A regression reproduced the skipped stop. HTTP destination validation accepted missing hosts and invalid ports, while malformed bracketed hosts could expose their contents in parsing errors. Nine configuration regression cases failed before the correction.

The runtime now owns detector and health futures and a shared cleanup scope that attempts every stop request before joining. The health adapter retains only timed requests and its stop signal. Bootstrap constructs the monitor without coordinating shutdown. Expected HTTP failures retain their retry behavior; unexpected health failures remain observable. Configuration validates HTTP destination hosts and ports once and uses static error messages, preserving valid URL strings exactly. No runtime dependency, generic worker framework, compatibility shim, complexity suppression or coverage exclusion was added.

| Final verification | Result |
| --- | --- |
| Python 3.10.18 | 237 tests passed |
| Python 3.11.13 | 237 tests passed |
| Python 3.12.0 with subprocess/branch coverage | 237 tests passed; 94.7% lines (1602/1692), 84.8% branch outcomes (341/402), 92.8% combined |
| Domain/application coverage | All measured lines and branch outcomes covered in both layers; coverage is not a correctness proof |
| Lifecycle behavior | Failed-close regression, finite EOF and real signal-driven draining pass with health monitoring; pytest now treats unhandled thread exceptions as errors |
| Ruff, formatting, ty and architecture | Passed; inward dependencies, safe imports and internal import-cycle checks remain enforced |
| Schemas and dependency lock | Schema check and offline lock check passed; configuration/schema files and lockfile match this iteration's starting snapshot |
| Complexity | Highest Ruff branch count remains 9. Maximum Radon score remains 15; five cohesive functions exceed 10, including the shared supervisor at 11. Function/method/closure count falls from 145 to 144 |
| Wheel and source distribution | Built offline; all 32 wheel source modules match current files byte for byte; all 42 allowed source-archive files match code/docs/package inputs and exclude local runtime artifacts |
| Installed wheel | Fresh Python 3.11 environment with runtime/default dependencies only; imports verified from site-packages; both ONNX and generated `.pt` smoke variants passed |
| macOS executable | Fresh Python 3.11/PyInstaller build; both ONNX and generated `.pt` smoke variants passed |
| Final review | Reviewed source/test changes against the saved starting snapshot and checked removed lifecycle references, documentation, package contents and repository whitespace |

The exact tested wheel has SHA-256 `239716b3e1a6b0b54595ae39501be91f3f0df7bb19dc4b1c0112a7a3bf2ae8b6`. All four distribution runs exercised two-source inference, structured verification through a localhost fake provider, real JPEG/MP4 archives, HTTP delivery, health monitoring and EOF shutdown. The frozen runs used the previously established macOS sandbox exception for PyInstaller's startup semaphore; application code required no workaround.

The resulting design was re-reviewed, and no further concrete finding from this iteration remains unresolved. The documented limits are unchanged: native Windows ML/CUDA/Jetson and GPU images require their target platforms; live cameras and real provider/notification endpoints were not used; active footage has duration/count bounds without a byte budget; SDK setup assumes one application per process. Two upstream Torch exporter deprecation warnings remain visible. Docker, release workflows, the dependency lock and all web files are unchanged in this iteration. No remote release, deployment or production action was performed.

## Code aesthetics and defensive-code findings resolved — 2026-09-18

The user authorized fixing all findings from the focused assessment. This pass started from 237 tests and addresses all seven findings within the existing architecture. [REVIEW.md](REVIEW.md) records each resolution, and [MIGRATION.md](../../../detector/MIGRATION.md) records the intentional provider-response and exception changes.

The media cache now uses separate typed image/video dictionaries and named immutable keys. Crop-only options no longer cause repeated original/annotated JPEG encoding; internal variant names explain those effects while archive filenames and attachment fields remain compatible. The provider response requires only the strict Boolean `detected`, removing the unused confidence/reasoning fields and their irrelevant floating-point validation option. Numeric type names now distinguish confidence, time and padding. Bootstrap and runtime construction use readable local values and statements. Duplicate batch-size enforcement and the ineffective CRF clamp were removed. Four test lambdas and three nested context-manager scopes were simplified.

Six regression cases failed before the fixes: four repeated-encoding cases and two Boolean-only provider answers. Additional cases cover distinct crop variants, video cache reuse/replacement, invalid response types/shapes and too few/too many SDK results. Existing assertions on public archive/notification behavior, failure propagation, resource release and shutdown remain intact.

| Final verification | Result |
| --- | --- |
| Python 3.10.18 | 252 tests passed |
| Python 3.11.13 | 252 tests passed |
| Python 3.12.0 with subprocess/branch coverage | 252 tests passed; 94.9% lines (1622/1709), 85.2% branch outcomes (341/400), 93.1% combined |
| Domain, application and rendering coverage | All measured lines and branch outcomes covered; this remains execution evidence, not a proof of correctness |
| Ruff, formatting, ty and architecture | Passed; all 56 Python files formatted, inward dependencies and import-cycle/safe-import checks pass |
| Schemas and lock | Schema and offline lock checks passed; configuration/archive schemas, config files, dependency definitions and lockfile match the starting snapshot |
| Complexity | Maximum Radon score remains 15; the supervisor decreases from 11 to 10, leaving four functions above 10. No gate or exclusion was changed |
| Wheel and source distribution | Built offline; wheel matches all 32 Python modules byte for byte; source archive contains 42 allowed files with matching included code/docs and no runtime data, recordings, weights, environments or reports |
| Installed wheel | Fresh Python 3.11 environment with runtime/default dependencies only; site-packages import location verified; ONNX and generated `.pt` smoke variants passed |
| macOS executable | Fresh Python 3.11/PyInstaller build; ONNX and generated `.pt` smoke variants passed |
| Final review | Compared source/test changes with the saved starting snapshot, checked remaining references, reviewed documentation and verified whitespace |

The exact tested wheel has SHA-256 `5dc2a2097991976b5ce4f6aff820abf800a320f5f5499478ed61f69431d53005`. All four package runs exercised two-source inference, the Boolean-only response through a localhost fake provider, real JPEG/MP4 archives, HTTP delivery, health monitoring and EOF shutdown. They also inspect the requested provider schema. Frozen runs used the established macOS sandbox exception required by PyInstaller's startup semaphore.

This pass also corrected the function-count methodology in QUALITY.md. Radon emits some closures both under their simple name and a qualified name. Counting unique file/line locations and confirming against the Python AST gives 142 functions/methods/closures at this pass's start and 143 after adding the callback that clears both typed caches. Earlier function totals recorded above included duplicate qualified closure entries. These counts are descriptive and are not used as a quality gate.

The smaller provider response is intentionally different. No real commercial provider or labeled-footage accuracy evaluation was run, so unchanged real-world detection quality is not claimed. The two upstream Torch exporter deprecation warnings remain visible. Native Windows/GPU execution, active-clip byte budgets and other retained tradeoffs are described in REVIEW.md. Docker, workflows and web files were unchanged in this pass; no deployment or production action was taken.

## Shared camera acquisition and SDK model downloads — 2026-09-19

Identical live source strings now share one capture and decoding thread within an application run. Bootstrap registers subscriptions before starting the capture pool. Each detector keeps independent sampling, size limits, bounded retention, tracking and event state; published arrays are read-only. Closing a subscription leaves other subscriptions active, and the pool owns reconnect and shutdown. Finite input readers remain independent.

The custom model HTTP read loop was removed. Stock model names retain Ultralytics' automatic asset resolution; URL transfers use its `safe_download`. Application code retains URL-specific cache destinations, temporary-file cleanup, atomic promotion and credential-safe diagnostics. URL downloads use one SDK attempt without curl fallback and follow SDK timeout behavior. Configuration and archive schemas did not change.

Verification:

- All **267 tests passed on Python 3.10, 3.11 and 3.12** on macOS. The two existing Torch ONNX-export deprecation warnings remain.
- Shared-source tests count actual capture-factory calls, exercise overlapping subscriptions, independent sampling/sizing/retention, shared reconnection, failure propagation and closing one reader. A generated ONNX model runs through two real YOLO trackers using one capture and writes an archive for each detector.
- Local HTTP integration tests execute Ultralytics' downloader for complete, empty, truncated and failed responses; they verify caching, filename collision isolation, recovery and diagnostic redaction. The stock-asset test preserves SDK lookup of `yolo11n.pt`.
- Ruff, formatting, source type checks, import/dependency checks, schema checks, wheel and source-distribution builds passed. Modified source functions remain within the enforced complexity limits; the capture loop's Radon score is 9.
- A newly built macOS ARM64/Python 3.11 executable passed ONNX and Torch smoke runs. Both download generated models from a loopback HTTP server through Ultralytics, perform inference, encode/archive JPEG and MP4, call local fake verification/export endpoints, report health and shut down at EOF. Release smoke tests now include those URL downloads.

The cameras in sharing tests are controlled capture doubles; inference, download HTTP, encoding and archives are real local integrations. No live cameras, external model weights, commercial services, Windows hardware, NVIDIA GPU or Jetson were used.

## Domain language and policy ownership — 2026-09-22

The DDD follow-up replaces the internal `Detection` and `Crop` names with `Observation` and `BoundingBox`. Events contain observations, observations contain boxes, and inference mapping, event assembly, rendering and their tests use that vocabulary consistently. The metadata adapter retains the public `detections` count and `crop` coordinates.

`Cooldown.record` now accepts the event's validation result together with the event and owns the acceptance rule. Application delivery passes the result without checking which statuses consume cooldown. Approved and intentionally unvalidated outcomes consume it; rejected and failed validation preserve previous state. Export eligibility and transport success remain separate decisions, with no change to alert cadence.

ARCHITECTURE.md documents the event-processing boundary, working vocabulary, producer contracts and state ownership. MIGRATION.md records the internal API names; user configuration and archives require no migration. No dependency, framework, compatibility alias, new domain hierarchy or repeated input guard was added. The earlier SDK reuse recommendations remain pending.

Verification:

- All **275 tests passed on Python 3.10, 3.11 and 3.12** on macOS, including architecture, local media, reference-flow, model-loading and integration checks. The two existing Torch ONNX-export deprecation warnings remain.
- Six new domain cases exercise the `record(EventResult)` contract across all four statuses and ensure rejected/failed validation neither clears nor extends a previous cooldown. These cases failed against the former API before implementation. Two application cases preserve cooldown after export failure, with and without configured verification.
- Ruff, formatting, source type checks and deterministic schema checks passed. Configuration and event metadata schemas are unchanged. The source/test review found no references to superseded internal types or helpers; retained public names are explicit boundary projections.
- Wheel and source-distribution builds passed offline. The built wheel's Python files match the current source byte for byte; the source distribution includes the updated architecture, migration and review documents.
- A newly built macOS ARM64/Python 3.11 executable in PyInstaller directory form passed both ONNX and Torch smoke runs. They download generated models from loopback HTTP, perform two-source inference, call local fake verification/export endpoints, encode and read JPEG/MP4 archives, report health and shut down at EOF.

No live cameras, external model weights, commercial providers, Windows execution, NVIDIA GPU or Jetson were used. The executable check used a directory bundle; the release workflow's single-file packaging was not rerun. This pass establishes the refactor's local behavior and packaging, not farmer validation of the vocabulary or model accuracy.

## Construction and SDK simplification — 2026-09-22

The new goal started from the 275-test implementation. All 32 source modules were reviewed for unnecessary objects, repeated configuration, resource ownership and work already supplied by installed libraries. Object relationships were traced through constructors and callers and compared with the system overview; no VS Code extension graph was executed. Independent reviews covered structure, runtime/source lifetime, inference/provider integration and media/delivery contracts.

`DetectionPipeline` now owns event assembly and directly handles processing without YOLO. This removes `PassthroughDetector` and the assembler's nullable-policy branches. `inference_runtime` replaces the lifecycle-only `OnnxRuntime` class with one cleanup scope. `open_detector` owns model preparation, class validation, predictor release and tracking-frame release together. Bootstrap no longer manages a raw SDK model and a separate detector cleanup callback. Fixed inference arguments are resolved once.

The previously assessed library substitutions are complete: Ultralytics draws boxes/labels and converts checkpoint paths, LiteLLM builds the strict response schema, and Pydantic validates HTTP destinations. The remaining adapter preserves clipping and image ownership, strict answer parsing, original valid URL text and restoration of both path-class globals after SDK loading. The changed annotation appearance was visually inspected with synthetic labeled, unlabeled and edge boxes. MIGRATION.md records the appearance, provider schema-name and malformed-URL acceptance changes; public configuration and archive schemas are unchanged.

The comparison with the saved starting snapshot gives **3102 → 3061 physical source lines, 68 → 66 classes and 152 → 146 function/method/closure definitions**. Module count remains 32. These are descriptive counts, including configuration models and data records. Highest Radon complexity remains 16, and the same five cohesive operations exceed 10. Shared capture, independent sampling, bounded delivery, failure supervision, media caching and explicit transport branches were retained after review because removing their distinctions would obscure required behavior.

| Final verification | Result |
| --- | --- |
| Python 3.10.18, 3.11.13 and 3.12.0 | 296 tests passed on each; two existing Torch export deprecation warnings |
| Coverage on Python 3.12 | 95.2% lines (1654/1737), 86.2% branch outcomes (357/414), 93.5% combined |
| Domain and application | All measured lines and branch outcomes covered; coverage is not a correctness proof |
| New behavior/lifetime contracts | Latest-frame immediate events, annotation ownership/clipping, strict URL rejection, cross-platform checkpoint loading, restoration after failures and release of tracked image memory pass |
| Ruff, formatting, source ty and architecture | Passed without new suppressions or weaker limits; highest Ruff branch count is 9 |
| Schemas and dependencies | Deterministic schema and offline lock checks pass; dependency definitions and lockfile match the starting snapshot |
| Wheel and source distribution | Built offline; all 32 wheel source modules and all 42 allowed source-archive files match current inputs byte for byte |
| Installed wheel | Fresh Python 3.11 environment with locked runtime/default dependencies only; site-packages import verified, dependency check passes, ONNX and generated Torch smoke variants pass |
| macOS executable | Fresh Python 3.11/PyInstaller directory bundle; ONNX and generated Torch smoke variants pass |
| Final source review | Removed-symbol references, constructor connections, changes against the saved snapshot, documentation links and whitespace reviewed |

The tested wheel has SHA-256 `d65460455ea246e5090d87a82b65a42080f539193445db399ef4e17093ad0db0`. Package runs download generated models from loopback HTTP, perform two-source inference, send the SDK-generated strict Boolean schema to a local fake verifier, encode/read JPEG and MP4 archives, deliver local webhooks, report health and stop at EOF. The executable and installed wheel both exercise the actual SDK serialization rather than a mocked request function.

No live cameras, external model weights, commercial providers, production destinations, native Windows execution, NVIDIA GPU or Jetson were used. The release's single-file packaging and GPU images were not rerun. Active clips still have duration/count bounds rather than a byte budget, and inference setup still assumes one application runtime per process; these retained limits are described in REVIEW.md. This completes the simplification goal's review and implementation without claiming an ideal design or personal endorsement by an architecture author.

## Architecture fitness and change measurement — 2026-09-22

The requested quality checks are now executable developer tools and CI steps. The existing hexagonal structure remains: domain rules and deterministic state, application use cases/ports, concrete I/O adapters and explicit bootstrap construction. All 32 production Python files match the previously verified package byte for byte. Runtime requirements and every existing locked package version are unchanged; 11 development-tool packages were added.

Import Linter replaces handwritten import parsing with four declarative contracts. Grimp supplies the graph for the retained core dependency allowlists and initializer-cycle checks. Ruff now owns the previous absolute-import convention. Negative tests insert real boundary violations into temporary source copies. Import safety is checked inside isolated children, including prohibited reads/writes, sockets, subprocesses, thread starts and logging changes; swallowed guard exceptions still fail. Normal interpreter/package metadata reads are permitted. Children exclude site/coverage startup hooks, and the probes are explicitly not security sandboxes for native code.

The first complete suite exposed Import Linter's CLI changing parent logging state, causing five existing diagnostic tests to fail. Its invocation now runs in a subprocess, with a before/after logging regression. The final full suites preserve all five assertions.

The report tool writes JSON and bounded Markdown for per-function Radon complexity/nesting, module fan-in/fan-out, dependency edge changes, Git-detected file changes and exact-path touches across the last 100 relevant non-merge commits. It uses explicit baselines and includes untracked source. Tests cover added/removed/renamed files, invalid baselines/source, absent packages, namespace directories, flat `elif` chains, nested functions, overloads and committed-history counting. Legacy namespace directories receive temporary graph-only initializers; synthetic files are excluded from metrics and never written to the repository. Repository-relative output paths are canonical POSIX paths. Native Windows execution was not performed.

The initial domain mutation run found 135 generated mutants: 117 killed, five survived and 13 without selected tests. Nine meaningful domain cases now catch all 135. They cover overlapping batches, source-specific flushing, fractional timeouts, cooldown defaults/unscored events and enclosing geometry. There were no production changes, new mutation pragmas or covered-line filters. mutmut's unsupported decorated properties and declaration coverage remain explicit limits.

| Verification | Result |
| --- | --- |
| Python 3.10.18, 3.11.13 and 3.12.0 | 356 tests passed on each; two existing Torch exporter deprecation warnings |
| Architecture/import safety | Four contracts kept; 44 focused tests pass, including deliberate violations and checks for logging isolation |
| Report tooling | 12 fixture tests pass; actual working-tree/HEAD and empty-baseline reports generated successfully |
| Mutation testing | 135 killed; zero survivors, missing tests, skipped, timeout, suspicious, interrupted or crashed outcomes |
| Production coverage | Unchanged: 95.2% lines, 86.2% branch outcomes, 93.5% combined; core lines/branches fully exercised |
| Lint/format/types/schemas | Ruff including absolute imports, formatting, source/tool ty, deterministic schemas and offline lock checks pass |
| CI configuration | YAML and shell syntax checked; mutation completion check exercised with complete, survivor, empty, crashed and inconsistent reports |
| Packages | Wheel and source distribution built offline; source archive includes `.importlinter`; analysis tools, tests and generated mutants stay out of runtime packages |

CI uses PR base SHAs and push-before SHAs, with explicit first-parent/empty handling when no previous revision exists. Quality JSON/Markdown are included in `detector-quality` and the workflow summary; mutation JSON/survivors have a separate `detector-mutations` artifact. Failed/incomplete mutation execution fails CI; survivors and missing tests are advisory review findings. Report artifacts are attempted even after earlier failures. No remote workflow, deployment or external message was triggered.

QUALITY.md records the source walkthrough for adding an exporter, changing an event rule and replacing inference, including expected configuration/wiring edits. Structural tests establish conformance to those boundaries; neither a diagram, the mutation result nor unchanged coverage proves general architectural correctness. No native executable rebuild was needed because this pass changes developer tooling, tests, documentation and CI only.

## Responsibility and location reassessment — 2026-09-22

The goal required a fresh review of code placement, Clean/Hexagonal Architecture and DRY, KISS, YAGNI, SRP, OCP, LSP, ISP, DIP, separation of concerns, modularity and the Boy Scout Rule. The current source and callers were inspected independently across domain/application, adapters and developer tooling, with root review of composition, configuration, runtime and CLI. REVIEW.md now records the present design and a principle-by-principle evidence matrix; older verification remains here rather than being repeated as current guidance.

Five production modules changed:

- ONNX provider setup now receives `OnnxConfig` plus immutable `ModelRequirements(path, image_size, batch_size)`. Bootstrap owns projection from detector definitions. The adapter no longer traverses application-wide configuration, and provider profiles are computed once per setup.
- Archive media writing and timestamp selection/publication are separate named operations in the same storage adapter. Publication still writes matching metadata and atomically renames completed staging. Tests cover both collision error forms and an unrelated publication error, preserving a competing archive and cleaning failed staging.
- Ordered delivery keeps only the first unexpected exception, while attempting and logging every independent destination. The existing multi-failure test now verifies the exact exception object that propagates.
- Port documentation states ordering, borrowed-data ownership, generator cleanup, repeatable stopping and expected/unexpected failure semantics. No new port or layer was introduced.

Verifier tests now live in `test_validation.py` and consume a direct event fixture. The 31 existing verifier/transport cases are preserved; no global fixture framework was added. Runtime source instructions use `--no-dev`, while contributor setup retains development tools. A dry-run runtime sync and a fresh installed-wheel environment verified that this distinction excludes test/quality packages.

A final challenge exposed a gap in the architecture tests: injecting a forbidden domain-to-adapter import inside `TYPE_CHECKING` passed all four contracts. Import Linter and the core/cycle graph now include those imports. Six negative cases reject annotated reverse dependencies, cycles, Torch/OpenCV and NumPy outside the permitted model module. The sole external core type allowance is `domain.models` to NumPy; the unchanged no-site runtime probe still requires domain imports without third-party packages. Quality-report coupling measurements remain explicitly runtime-import based.

The remaining structure was retained after checking actual consumers and change scenarios. The compact domain/application/adapters packages, source pool, runtime supervision, encoding cache and verifier retry loops describe current behavior. Additional repository, registry, generic payload or dependency-injection frameworks would add concepts without simplifying a current use case. Static NumPy annotations and shallowly immutable borrowed arrays are explicit tradeoffs, rather than a claim of complete library independence. A misleading sentence about finite inputs was corrected: an event is completed and queued before the next file, but its asynchronous delivery may finish later.

| Final verification | Evidence |
| --- | --- |
| Python 3.10.18, 3.11.13, 3.12.0 | 371 tests passed on each; two existing Torch ONNX-export deprecation warnings |
| Architecture | Four contracts kept, 208 dependencies analyzed; 50 architecture/import-safety tests passed on each Python version |
| Required checks | Ruff, formatting, source/tool ty, deterministic schema and offline lock checks pass; no new suppression, exclusion or weaker limit |
| Coverage | 95.6% lines (1669/1746), 87.3% branch outcomes (363/416), 94.0% combined; domain 184/184 lines and 50/50 branches, application 103/103 and 20/20 |
| Targeted mutation run | 135 generated mutants killed; zero survivors, missing tests, skipped, timeouts, suspicious, interrupted or crashed outcomes; decorated properties remain outside the tool's scope |
| Source measurements | 32 modules; 3061 to 3105 physical lines, 66 to 67 classes, 146 to 147 definitions; added lines chiefly document behavioral contracts and the narrow model input |
| Complexity | ONNX setup 9 to 7, TensorRT profiles 6 to 4; archive writing 11 to 7, publication 5; highest remains 16 and functions above 10 fall from five to four |
| Runtime contracts | Configuration and metadata schemas, runtime requirements and existing dependency versions are unchanged |
| Distribution | Offline wheel/sdist built; runtime files match source and developer artifacts stay excluded; sdist contains the strengthened import contracts |
| Installed wheel | Fresh Python 3.11 environment with locked runtime/default dependencies only; imports resolve to site-packages, dependency check passes, ONNX and generated Torch smoke variants pass |
| macOS executable | Fresh ARM64 Python 3.11.13/PyInstaller 6.21.0 directory bundle; both ONNX and generated Torch smoke variants pass |

Full-suite logs are `/tmp/ai-detector-architecture-final-python310.log`, `-python311.log` and `-python312.log`; measured coverage is `/tmp/ai-detector-architecture-final-coverage.json`. Mutation results are also copied into `detector/.reports/mutations.json`. The current HEAD comparison is `detector/.reports/quality.md` and JSON. The packages are in `/tmp/ai-detector-architecture-dist`, and the native executable is `/tmp/ai-detector-architecture-native/dist/aidetector/aidetector`.

Both installed-wheel and native smoke variants use generated models, two local video sources and loopback services. They exercise SDK model download/cache, inference, strict VLM schema and response parsing, real JPEG/MP4 archives, HTTP delivery, health monitoring and normal EOF shutdown. All 32 source hashes remained stable through the native build and smoke checks. No live cameras, production destinations, commercial providers, native Windows execution, NVIDIA GPU or Jetson were used. The release's single-file packaging and GPU images were not rebuilt; remote CI was not triggered. These limits do not imply that static architecture checks establish platform or model accuracy.


## Developer navigation cleanup — 2026-09-22

Grouped the existing inference and media modules, gave image/event-media/VLM adapters specific names, and organized tests by production responsibility with subprocess/model helpers under `tests/support`. The README now supplies a contributor reading path and change-to-test map. Internal import and executable smoke paths changed together; configuration, archive formats, entrypoints and runtime dependencies did not change.

- Production comparison found identical behavior after accounting for module imports, ownership docstrings and the shared `MediaError` location. Source now has 34 modules, including two new package initializers, with the same 67 classes and 147 callable definitions. All 193 test functions and 599 assertions are preserved.
- All 371 tests pass on Python 3.12.0. Ruff, formatting, ty, four architecture contracts, import-safety probes and schema checks pass. Measured coverage is 95.6% of statements and 87.3% of branches; domain and application have 100% of both. Complexity is unchanged. The mutation selectors were relocated; mutation execution was not repeated for unchanged domain code and test bodies.
- Wheel and source distribution build successfully. The wheel contains all relocated adapters, no superseded adapter files, and no test/tool modules. Imports and CLI version/init/check operations pass from the installed wheel outside the checkout using the development environment's dependencies.
- A fresh macOS ARM64/Python 3.11.13 directory executable passes both generated ONNX and Torch smoke runs: local model downloads, two-source inference, local VLM verification, real JPEG/MP4 archives, HTTP delivery, health and EOF shutdown. Logs are `/tmp/ai-detector-clarity-smoke311-onnx.log` and `/tmp/ai-detector-clarity-smoke311-pt.log`; build output is `/tmp/ai-detector-clarity-native311/dist/aidetector`.

A preliminary frozen build with CPython 3.12.0 failed in `torch._numpy._ufuncs` with a `NameError`. A standalone comprehension/loop reproduction fails after `code.replace()` on 3.12.0 and passes on 3.11.13; PyInstaller invokes that operation while rewriting code filenames. Torch, PyInstaller and hook versions match across the environments. The failure is independent of the application imports, and no application workaround was added. Release workflows already use Python 3.11; the contributor guide now makes this explicit. Newer 3.12 patch versions were not assessed.

No native Windows, NVIDIA/Jetson, live-camera or production-service validation was performed. Single-file packaging was not rerun. Local reference flows and packaged smoke checks use temporary data, generated models and fake/local services.

## Adapter grouping and configuration names — 2026-09-22

Moved detection-event destinations into `adapters/exporters/`, including the archive's metadata model under `archive_metadata.py`. Moved file readers and live subscriptions/pools into `adapters/sources/`. Health monitoring, shared HTTP transport and VLM verification remain direct adapter modules. Related domain records, policies, application ports and runtime supervision stay together; no generic utilities, forwarding modules or new runtime abstractions were added.

Renamed `DetectionConfig` to `SourceConfig` and `ChatConfig` to `TelegramConfig`. Public JSON keys, field defaults and validation rules remain unchanged. Generated schema definitions and references follow the renamed classes; metadata schema bytes are unchanged. Comparison against a temporary copy of the pre-change working tree found all 34 existing production module ASTs identical after accounting for imports and those two class names. Source now has 36 modules, the same 3,120 physical lines, 67 classes and 147 callable definitions.

Tests follow the adapter folders. Domain tests are split by event assembly, policy and models, preserving all 22 original functions, parameterized cases and 49 assertions. Mutation selection includes all three domain files. No new mutation run was performed for unchanged domain code and test bodies.

The fifth Import Linter contract forbids dependencies between sources, inference and exporters while permitting their shared media/HTTP dependencies. Seven negative cases cover all six directional group dependencies, deferred and annotation-only imports, and an indirect path through shared media. Existing layer and cycle rules remain in force.

Verification:

- All 378 tests passed on macOS/Python 3.12.0, including the real media/reference flow, with the two existing Torch ONNX-export deprecation warnings. Ruff, formatting, ty, schema regeneration checks, offline lock checks and all five architecture contracts passed.
- Coverage is unchanged: 95.6% of statements (1671/1748), 87.3% of branches (363/416); domain and application retain 100% of both. Radon hotspots and limits are unchanged. Current coverage and dependency reports are under `.reports/`.
- Wheel and source distribution build successfully. The wheel contains exactly the 36 current source modules, matching their bytes, and excludes superseded paths, tests and tools. Installed imports resolve outside the checkout.
- The installed wheel passes both ONNX and Torch model smoke variants on Python 3.11.13 using existing locked dependencies: local model download/cache, two-source inference, fake local VLM verification, real JPEG/MP4 archives, HTTP delivery, health and EOF shutdown.
- Current documentation links resolve. The architecture guide includes the new package map and dependency diagram; migration notes distinguish Python/schema-definition renames from the unchanged configuration document. The earlier local class-review report is explicitly marked as a historical snapshot.

Logs, coverage data, packages and the pre-change comparison snapshot are in `/private/tmp/detector-grouping-9k3pq3e1`. Native executables, Windows/NVIDIA/Jetson hardware, live cameras and production services were not rebuilt or exercised during this pass. No web implementation or shadcn components changed.

## Contributor contracts, diagnostics and feedback — 2026-09-22

Completed all seven findings from the fresh onboarding review:

- Architecture tests compare all filesystem Python modules with Grimp discovery. A copied-source negative case adds a forbidden domain-to-disk dependency under a directory without `__init__.py`; completeness fails until the initializer is restored, at which point Import Linter rejects the dependency.
- Bootstrap assigns diagnostic names by detector configuration order. The processing thread temporarily takes `detector-N-processing`; its delivery thread uses `detector-N-delivery`. CLI formatting includes those names. Tests cover distinct concurrent failure identities, real two-detector CLI delivery errors, and restoring the caller's name after success/failure. Queueing, supervision, cleanup and statistics semantics remain unchanged.
- `SourceBatch.captured_at` is renamed to `advance_to`, with frame/idle/media-time semantics documented. Record/port docstrings specify borrowed read-only uint8 BGR image arrays and nonempty chronological events. A local cleanup comment explains ExitStack's reverse execution order; the event-boundary comment matches the existing rule.
- Source and destination builders receive `SourceConfig` and `ExportersConfig` respectively. Callers pass the corresponding nested settings instead of exposing an entire detector configuration.
- Sixteen cases exercise HTTP success/status/exception boundaries, Telegram malformed/rejected acceptance, continued independent delivery with credential-free diagnostics, and complete `ALL` archives with context, duplicate timestamps and real media.
- Moved disk-only publication/stage tests and file-only sampling tests beside their adapters, preserving their function bodies/decorators/assertions. The existing video generator moved to `tests/support/media.py`; the root reference flow retains three cross-layer test functions/four cases.
- Added VS Code process tasks, test discovery and an offline reference-flow debug profile. The interpreter setting uses the environment directory for cross-platform discovery. The contributor guide documents interpreter selection, debugging, task scope, test locations and log identity. Architecture guidance correctly assigns destination filtering to `EventDelivery` and `ExportPolicy`.

All 397 tests pass on macOS/Python 3.12.0, with two existing Torch ONNX-export deprecation warnings. Ruff, formatting, ty, five import contracts, graph completeness, schema checks and the offline lock check pass. Public config/metadata schemas are byte-identical to the preceding pass; no runtime dependency changed. Statement coverage is 95.8% (1679/1752), branch coverage 88.0% (366/416), combined coverage 94.3%; domain/application remain at 100% of measured statements and branches. There are still 36 production modules, 67 classes and 147 callable definitions; physical lines rise from 3120 to 3149. Complexity hotspots are unchanged. Domain behavior and mutation selectors are unchanged; mutation execution was not repeated.

Executed the configured VS Code lint, formatting, type and schema task commands. The full suite includes the architecture task's checks. A temporary DAP client launched the checked-in debug profile through the installed Python Debugger extension, fulfilled its integrated-terminal request and set a real breakpoint in `EventDelivery.deliver`. The breakpoint was verified and hit twice; continuing both stops produced two passing reference-flow cases and exit code 0. This tests the debug adapter/profile, not interactive VS Code UI navigation. The normal DAP launch had no frozen-module warning and needed no additional interpreter arguments or project dependency.

Wheel and source distribution builds pass. Logs, coverage data, debugger evidence and package artifacts are in `/private/tmp/detector-onboarding-f81jz7jk`; current coverage/quality reports are under `detector/.reports/`. No native executable rebuild, target GPU/Windows/Jetson execution, live-camera or production-service test was performed. The web implementation and shadcn components were not modified.
