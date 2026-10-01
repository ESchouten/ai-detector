# Detector migration

The rebuild covers the Python detector, its schemas, tests, and distributions. The Python rewrite preserved the web archive contract. The subsequent application setup work adds a combined web/native download and optional parent-controlled shutdown.

## Compatibility commitments

- Existing top-level `detectors`, `onnx`, and `health` configuration remains supported.
- Single values and lists remain accepted for sources, VLM configurations/models, and exporters.
- Existing VLM configurations remain enabled by default. Presets may now retain a question with `enabled: false` and no model; only enabled entries run. The detector-level `vlm_enabled` switch defaults to `true`; setting it to `false` pauses the list without rewriting individual enabled flags. Optional `headers` are passed to the provider. A deliberately empty `key` selects a service without key authentication, while an omitted key preserves provider/environment lookup. The web app's shared AI connections are expanded into the existing per-detector `vlm` fields on save, so Python needs no web metadata. `--test-vlm FILE` checks a connection with synthetic media without starting detection.
- YOLO detection/segmentation, stable per-source tracking, class thresholds, collection windows, cooldowns, optional validation, disk, Telegram, webhook, and health pings remain available.
- Existing `detections/<category>/<stage>/<timestamp>/` archives remain readable. New archives keep best.jpg, clean.jpg, optional video.mp4, and metadata.json with the existing required fields.
- Runtime data is kept separate from installed source. Existing live config and detection archives are not modified by the rewrite or its tests.
- Docker, macOS, Windows CUDA, and Windows ML packaging remain supported; actual provider execution can only be verified on available hardware.

## Release build and container caching — 2026-10-01

Native build and installer jobs now progress independently per OS, with publication gated on all checks. The NVIDIA bootstrap installation test runs in parallel using the same staging function as the Windows payload. PyInstaller delegates ImageIO FFmpeg and ONNX Runtime library collection to their upstream hooks; model and provider support is unchanged. Linux installers use Zstandard level 9, Windows deltas use Velopack's BestSpeed strategy, and Sparkle deltas use LZFSE compression.

Container base images are pinned by digest. Dependency installation precedes source copying and version stamping, so code-only releases reuse those layers. Runtime dependencies still respect the upstream image's Torch constraints. Standalone image release tags require native builds and startup checks for both architectures, the component test suite and workflow lint. macOS installers no longer wait for or include the NVIDIA Docker image reference. These changes do not migrate configuration or recordings.

## Manual recording review — 2026-09-30

Each delivered event now has a UUID assigned by the delivery use case. Independent exporters receive the same ID; disk stores it as optional `event_id` metadata and Telegram uses it in language-independent 👍/👎 callback buttons. Existing metadata without IDs remains readable and reviewable in the web app. Telegram albums receive a silent button message replying to the first album item. The web server receives callbacks and writes manual review sidecars; Python does not consume Telegram updates or alter completed archives.

Manual reviews change display/filter/export classification, never inference, validation, cooldowns or alert policy. Original metadata and media remain unchanged. The existing configuration schema needs no migration. Internal `EventResult` constructors now require an ID; pure domain rules do not generate identities.

## Optional direct TensorRT on Windows NVIDIA systems — 2026-09-30

Automatic Windows NVIDIA startup now downloads TensorRT for compute capability 8.0+ after preparing working CUDA. Ultralytics exports a checkpoint copy on the local GPU and tests the resulting engine before caching it under `models/prepared/tensorrt/`. Inference then loads that engine directly; ONNX remains only an export intermediate. Older supported GPUs keep native PyTorch/CUDA. Explicit ONNX providers and supplied `.onnx`/`.engine` models are unchanged. The desktop passes an internal flag; no JSON field, preset change or new onboarding step is introduced.

The optional packages are separate from the base CUDA lock. Engine cache identities additionally include GPU/driver/runtime versions. Failed optimization attempts retain diagnostics and use PyTorch/CUDA; subsequent starts defer the same failed attempt for 24 hours. Pause/quit terminates preparation, and builds have a ten-minute deadline. Inference failures still reach the existing process supervisor. This does not promise bit-identical predictions or measured speed gains: FP16 conversion needs representative accuracy and performance checks on the target GPU. Resolution, thresholds, sampling, event rules and archives stay unchanged.

## Native CUDA on Windows NVIDIA systems — 2026-09-30

The application's automatic NVIDIA runtime selection now also applies to Windows 11 24H2 and newer. Supported NVIDIA GPUs use the existing downloaded PyTorch/CUDA environment on every supported Windows version; `.pt` models run directly without ONNX conversion. The log identifies the selected GPU and native CUDA route. Hardware requirements, dependency caching, explicit ONNX provider choices and failure handling are unchanged. Camera sampling, presets and archives are unchanged. This changes the packaged application's process selection, not standalone detector behavior.

## Shared frame resizing and performance diagnostics — 2026-09-30

Live detectors requesting the same frame width now share one resize operation per decoded frame. Pixel values, sampling, retention, model precision, inference resolution, event rules and configuration are unchanged. Skipped samples do not trigger resizing. Logs break down inference stages and periodically report capture/publication costs. The new developer benchmark compares local PyTorch and TensorRT models and experimental shape grouping without changing the running application's batching. GPU performance and accuracy require measurement on the target system with representative data; automatic TensorRT selection is described separately above.

## Continuous managed detector recovery — 2026-09-30

Enabled monitoring now retries every unexpected detector exit, including exit zero, termination signals and hard process crashes. The previous limit of one MPS recovery per ten minutes is removed. Retries wait 2, 4, 8, 16 and then 30 seconds without an attempt limit; ten minutes of running resets the delay. Failed recovery or resumed-startup checks also retry. Errors and restart timing remain visible, diagnostic logs survive automatic recovery, and readiness resets until the new process processes fresh frames. Pause and quit suppress recovery. Managed monitoring restarts completed finite inputs too; standalone CLI jobs still finish at EOF. Applying saved settings resumes monitoring even if the old process fails while draining. Python inference, CLI exit statuses, configuration and archive formats are unchanged. Mac and Windows native launchers also restart an unexpectedly exited web process. Losing the native menu alone leaves the web process and monitoring running; reopening the app reattaches the menu.

Shutdown logs now distinguish explicit parent commands from control-pipe EOF. The application also records monitoring disablement, configuration restarts, OS signals and native-launcher shutdown reasons in its saved log, retaining those diagnostics across configuration restarts. The existing graceful shutdown behavior and exit codes are unchanged. A reported launcher shutdown with exit zero can therefore be traced to its origin rather than assumed to be either a detector crash or a deliberate user action.

## ONNX CPU scheduling and diagnostics — 2026-09-30

ONNX sessions explicitly disable intra-op and inter-op worker spinning. Idle workers sleep instead of spending CPU time polling for work; parallel computation and provider selection remain available. This applies to registered Windows ML devices and ordinary ONNX providers. Native PyTorch/CUDA/MPS execution, camera sampling, model precision and configuration are unchanged. The scheduling tradeoff can affect latency, so compare throughput on the target hardware.

Startup logging now distinguishes the loaded ONNX session's provider list from the device Ultralytics uses for image tensor processing, and reports whether I/O binding is active. A CPU image tensor device does not prove the model runs entirely on the CPU; a GPU provider in the list does not prove every graph operation runs there either. Per-operation placement requires runtime profiling.

## FP16 model preparation — 2026-09-28

FP16 ONNX exports now pass through ONNX Runtime's graph ordering before validation and cache publication. CPU-based FP16 conversion can append cast nodes after their consumers, causing an otherwise usable export to fail the ONNX checker. Precision, model metadata, external weights and configuration remain unchanged; invalid graphs still fail validation. Failed exports were never cached, so retrying after an application update rebuilds them automatically.

## Restore operational logging — 2026-09-25

The default `INFO` level again shows prediction/tracking timings and Ultralytics detection summaries, alongside startup, camera connection, event, validation, cooldown and export diagnostics. These messages were missing or debug-only after the rewrite. Camera success is reported only after decoding a frame; delivery success only after the exporter returns. Source URLs and configuration secrets stay out of the new diagnostics. `--log-level WARNING` suppresses routine activity. Model settings, event rules, configuration and the separate launcher status protocol are unchanged.

GPU bounding boxes now move to CPU memory once through Ultralytics before mapping their scalar values. This removes repeated MPS/CUDA synchronization without changing model output, confidence thresholds, coordinates or tracking IDs. Live inference still scores only the newest retained frame per source; older retained frames provide event context. The ordinary web preview continuously drains FFmpeg and retains only the latest complete JPEG while its browser is slow, avoiding upstream playback backlog. Neither change increases the number of frames submitted to inference.

## Live camera responsiveness and alert ownership — 2026-09-25

Live network capture uses one FFmpeg decoder thread to avoid frame-thread buffering and allows ten seconds for opening or reading a stream, replacing the overly short three-second timeout. Camera sharing, per-detector sampling, event windows, thresholds and delivery policy are unchanged. Analyzed previews now publish up to eight times per second while viewed, using the same bounded latest-frame transport. Packaged applications keep Matplotlib's font cache under `cache/matplotlib` in their data directory, avoiding a complete font scan on each launch.

The web alert editor again assigns recipients to detectors. It no longer splits multi-camera detector definitions to represent camera-level notification choices. Saving alert assignments changes only Telegram destinations; camera lists, models, event settings and other exporters remain intact. Existing configuration files are accepted without a schema migration or automatic merging of previously split detectors. Reading settings does not rewrite them.

## Linux desktop dependencies — 2026-09-25

The `default` extra now selects CPU builds of Torch and Torchvision on Linux. Native desktop installers no longer bundle unused CUDA libraries that pushed downloads beyond GitHub's release asset limit. The `nvidia` extra keeps GPU dependencies, and macOS keeps MPS support. uv now enforces the existing rule that `default`, `nvidia`, and `windowsml` are alternative environments. Models, configuration and detection archives are unchanged.

## Intentional corrections

Packaged Windows applications prepare an NVIDIA environment on first use for supported NVIDIA GPUs (compute capability 7.5+, driver branch 572+) on Windows 10 and Windows 11. Its pinned Python/CUDA dependencies are downloaded into the data directory and reused across app updates. It runs the same detector code through the native CUDA route, retaining configuration, presets, archives and lifecycle protocols. Explicit ONNX provider selections and systems without a supported NVIDIA GPU retain their existing routes. Interrupted preparation is retryable; installation or GPU-check failures remain visible. Standalone detector executables do not install this environment themselves. The desktop launcher accepts Windows 10 22H2 and newer.

These are behavior decisions, not accidental compatibility changes. Their tests are added with the corresponding implementation.

- Invalid configuration fails before processing. Reading configuration does not repair or overwrite it.
- Defaults do not depend on whether Torch reports CUDA availability. The omitted `frames_min` default becomes 3 on all platforms; set it to 6 explicitly to retain the old CUDA default.
- `frames_min` means matching observations in an event, as implemented previously. It does not require consecutive frames.
- Finite videos use media time. EOF and shutdown flush an eligible pending event.
- Configured validation failures are distinct from disabled validation. Failed verification does not send ordinary external notifications; an archive may retain the event as unvalidated with the failure recorded.
- Source acquisition reconnects only on expected input failures. Invalid config and unexpected application errors do not restart forever.
- Outbound requests and queued delivery work are bounded.
- Existing event folders are never overwritten by a second event with the same timestamp.
- Obsolete/unknown configuration options are reported. The old README's `yolo.strategy` was not implemented.
- Config creation is explicit (`--init-config`); a missing file is an error during normal startup. No template or schema is fetched over HTTP.
- Relative media/model paths resolve against the config directory. Runtime output defaults there, or to `--data-dir`. Downloaded models live in its `models/` directory.
- Disk `directory` must be a single category name under `detections/`, such as `mounts`. Nested paths, absolute paths, blank names, and dot-only names are rejected because they break archive discovery. Move an old absolute output root to `--data-dir` and choose a single category name.
- Put finite files and live streams in separate detector definitions. Each finite file now closes its event before the next file starts.
- Provider calls and webhook/Telegram requests default to a finite timeout. VLM retry attempts and pending delivery events are configurable; shutdown drains accepted events and can wait for these requests.
- Current source installations require Python 3.12 or newer. Development, CI and native executables use the shared `.python-version` pin; see the Python migration section below.
- Buffered frames are assigned to event windows in timestamp order, preserving eligible trailing footage before a timeout or maximum-duration boundary.
- Signed ONNX URLs receive the same runtime setup and provider validation as local ONNX models in CUDA and TensorRT builds.
- Missing FFmpeg is reported as a verification or delivery failure. Independent destinations continue to be attempted.
- Telegram photos are compressed to a 10 MB limit; the detector's video limit remains 12 MB.
- Cropping preserves the detected region when the source image is too narrow or short for the preferred aspect ratio. Encoded clip dimensions can consequently differ from earlier crops that cut off part of a detection.
- Local media filenames containing `#` or `?` are interpreted literally where the filesystem permits them; query/fragment parsing applies to HTTP(S) URLs.
- Temporary video-storage failures use the existing media-failure outcome, so independent destinations can still be attempted.

- The offline config check now rejects mixed finite/live sources, unsupported protocols, missing URL hosts, and HTTP image URLs. These inputs previously failed later or reconnected indefinitely. Supported local images, HTTP video, streams, and camera indices keep their existing representation.
- Native Torch model setup now applies the selected inference precision. CUDA builds can consequently use FP16 as intended; actual GPU execution still requires validation on the target hardware.
- JPEG codec exceptions follow the existing media/delivery failure policy. A verifier whose media cannot be encoded yields to the next configured verifier strategy; exhausting all verifiers remains an explicit failure.
- Verifier fallback now distinguishes malformed provider answers from unexpected SDK/programming errors. Empty or invalid answers still try the next model; unexpected `IndexError` or `ValueError` failures stop the worker and remain visible instead of being reported as ordinary verifier unavailability.
- A partially started live source now stops its already-started capture threads. Concurrent capture/detector failures each produce a diagnostic before the first failure reaches the supervisor. Archive stage names, metadata, configuration, event timing and notification policies are unchanged.
- Health monitoring now shares the runtime supervisor with detection. A failed source close no longer aborts the stop requests for the remaining tasks. Expected health HTTP failures still log and retry; unexpected health-worker failures stop detection and reach the caller. Finite EOF and signal shutdown join the health monitor before application resources are released.
- The offline config check rejects health/webhook URLs without hosts or with invalid/out-of-range ports. Malformed URL errors no longer repeat raw parser input. Valid URL strings are preserved; configuration and archive JSON schemas are unchanged.
- VLM requests now ask only for `{"detected": true}` or `{"detected": false}`. The unused `confidence` and `reasoning` response fields have been removed. Custom provider implementations and response fixtures must follow the requested schema; extra fields remain invalid. Approval/rejection, retry ordering and fallback rules are unchanged. The smaller schema can affect real model responses, so compare accuracy on labeled footage before a production rollout. No commercial provider was contacted during local verification.
- Original and annotated JPEGs share their cached encoding across destinations with different crop-only options. Internal variant names are clearer, while archive filenames and notification attachment names remain unchanged.
- YOLO result-count mismatches are enforced by strict batch pairing. They still fail the worker; the underlying exception is now `ValueError` from strict `zip` instead of a separate `RuntimeError` check.
- Detector definitions using the same live source string now share one camera connection and decode operation per frame within an application run. Each detector retains its own sampling interval, frame size, unread retention, tracking and event state. Shared images are read-only. Closing one subscription does not close another detector's camera; application shutdown releases the shared captures. Finite sources keep independent readers and media-time scheduling. No configuration changes are required.
- Explicit model URLs now download through Ultralytics' `safe_download`, while standard model names keep its automatic asset loading. Existing cache paths remain valid. URL cache separation, temporary-file cleanup, atomic completion and credential-free diagnostics are preserved. Custom URL transfers use a single SDK attempt without its curl fallback; network timeout behavior follows the SDK instead of the previous custom 30-second request timeout.

## Internal domain API cleanup — 2026-09-22

Internal Python names now reflect their meaning: `Detection` becomes `Observation`, `Crop` becomes `BoundingBox`, `DetectionEvent.detections` becomes `observations`, and `Observation.crops` becomes `boxes`. The enclosing region is `Observation.enclosing_box`. Inference mapping and media helpers use the same vocabulary. Superseded names have been removed.

`Cooldown.record` now receives an `EventResult` and owns the validation-outcome rule. Approved and intentionally unvalidated events consume cooldown; rejected and failed validation leave it unchanged. Delivery failures still do not undo acceptance. This moves responsibility without changing runtime policy.

Configuration, metadata fields (`detections`, `crop`), archive paths and the web reader contract are unchanged. No user configuration or archive migration is needed. Custom Python integrations must use the renamed internal types and fields.

## Construction and SDK simplification — 2026-09-22

`DetectionPipeline` now receives an optional detector and an `EventPolicy`, and constructs its own `EventAssembler`. `DetectionPipeline()` directly emits the latest unscored frame per source. `PassthroughDetector` and `EventAssembler(None)` have been removed; event timing, EOF and shutdown behavior remain unchanged.

Use `inference_runtime(onnx_settings, models, build_type)` instead of `OnnxRuntime`. `models` is a tuple of `ModelRequirements(path, image_size, batch_size)` projected by bootstrap; the provider adapter no longer accepts the complete application configuration. Use `open_detector(config, onnx, sources, build_type, options)` instead of opening a model and constructing a `YoloDetector` separately. This context yields the ready detector and releases its predictor and tracking frames. The separate detector `close()` method is removed. Ultralytics handles cross-platform checkpoint paths; the adapter restores the path-class globals after loading.

Box and label rendering now uses Ultralytics' `Annotator`; label placement and line styling can differ. Coordinates, crop geometry and raw images retain their existing behavior. LiteLLM builds the structured-response schema from the Pydantic answer model; the request's schema name changes from `detection_result` to `_Answer`. The strict Boolean answer contract and fallback rules remain unchanged.

Health and webhook URLs now use strict Pydantic validation. Malformed hosts, whitespace and URLs requiring repair fail the offline config check. Accepted URL strings retain their original representation. Configuration and archive schemas remain unchanged; no data migration is required.

## Source URL validation — 2026-09-23

Camera and HTTP media URLs now use strict Pydantic validation with the supported protocols and a required host. Invalid/out-of-range ports, hostnames containing spaces, and embedded control characters fail the offline configuration check before opening a capture. URL failures use one credential-free message describing the accepted protocols, host and port requirements. Valid source strings, including IPv6, multicast addresses and encoded credentials or queries, retain their original representation. Camera indices, local files, source grouping and JSON schemas are unchanged.

## Developer navigation cleanup — 2026-09-22

The internal adapter modules now group related operations. `adapters/media.py`, `video.py` and `rendering.py` become `adapters/media/images.py`, `media/video.py` and `media/event_media.py`. `MediaError` belongs to the `adapters.media` package. `adapters/model_files.py`, `onnx.py` and `yolo.py` become `adapters/inference/model_assets.py`, `inference/onnx.py` and `inference/yolo.py`. The concrete verifier is `adapters/vlm.py`, previously `validation.py`. Internal Python callers must use these paths; no forwarding modules remain.

Tests mirror the domain, application and adapter responsibilities; CLI, configuration, runtime and whole-application checks remain at the test root. Subprocess and model-building helpers live under `tests/support/`. Executable smoke checks now run with `python -m tests.support.smoke_package`. Mutation selectors and release workflows use the relocated tests. The README is the contributor entry point, with a source reading path and a change-to-test map.

These changes preserve event rules, resource lifetimes, configuration, archive formats, command-line entrypoints and runtime dependencies. No user data migration is required.

## Adapter grouping and configuration names — 2026-09-22

Event destinations now live in `adapters/exporters/`: `disk.py`, `telegram.py`, `webhook.py` and `archive_metadata.py` (formerly `adapters/metadata.py`). Frame acquisition lives in `adapters/sources/files.py` and `sources/streams.py`. Update internal Python imports to these paths; superseded modules and forwarding aliases are not retained. Health monitoring, shared HTTP transport and VLM verification remain directly under `adapters/`.

`DetectionConfig` is now `SourceConfig`, and `ChatConfig` is now `TelegramConfig`. Existing configuration documents still use `detection` and `telegram`; their fields, defaults and validation rules are unchanged. Generated JSON schema definition names and their references follow the renamed Python classes. Tools referring directly to those `$defs` names must update them. Archive metadata is unchanged.

Adapter tests follow the new folders. Domain tests are separated into `test_events.py`, `test_policy.py` and `test_models.py`; mutation selection includes all three. Import Linter enforces independence between exporters, sources and inference, including indirect and annotation-only imports. Shared media/HTTP imports remain allowed. No user configuration or archive migration is required.

## Contributor contracts and diagnostics — 2026-09-22

The internal `SourceBatch.captured_at` field is now `advance_to`, reflecting its purpose as an optional event-clock advancement signal. Update Python callers using that keyword; its position and behavior are unchanged. The source/event records now document existing BGR image, borrowed ownership and chronological event invariants without adding runtime guards.

Bootstrap's `build_source` helper takes `SourceConfig`, and `build_destinations` takes `ExportersConfig`, instead of accepting a complete `DetectorConfig`. Pass the corresponding nested settings from internal Python callers. Processing/delivery logs include a detector ordinal based on configuration order; worker execution restores the caller's thread name afterward. Shared capture and health work retain separate identities. Configuration documents, schemas and archive formats remain unchanged.

Architecture tests now reject Python modules omitted from the import graph, including folders missing `__init__.py`. Source-only and disk-only tests moved out of `test_reference_flow.py`; that file retains the cross-layer example used by the new VS Code debug profile. VS Code tasks invoke the existing tools and require the same locked development environment; no runtime dependency was added.

## Rollout and recovery

The model-preparation cleanup separates conversion selection, SDK loading and predictor setup while retaining one context-managed owner. Cached and direct exports now share their argument construction. Existing model caches, configuration, provider choices and archive formats remain compatible; no migration is required.

On macOS, `.pt` checkpoints now use native PyTorch MPS with FP16 when the device is available and no `onnx.provider` is explicitly configured. This avoids exporting those checkpoints to ONNX. An explicit provider retains ONNX preparation, and an unavailable MPS device retains the existing automatic ONNX route. `.onnx`, `.engine`, CUDA and TensorRT behavior is unchanged. Model errors remain failures; they do not silently choose another backend. Existing prepared ONNX cache entries are left intact.

Native MPS inference now takes turns across detectors, holding one shared lock through GPU result transfer and synchronization. This mitigates known PyTorch/Metal threading races while retaining FP16 GPU execution. Camera capture, event rules, confidence thresholds and other backends are unchanged; simultaneous MPS batches may spend time waiting for the GPU. The reported intermittent indexing crash still needs confirmation on the affected Mac; a passing stress test is not proof of long-running stability.

If native MPS inference raises `torch.AcceleratorError`, the detector exits with code 75 after normal cleanup, preserving the traceback. The managed application restarts using the same settings and GPU backend through the continuous recovery policy described above. Pause and quit cancel recovery. Previous log output remains available, and readiness must be established again by the new process. Standalone CLI runs do not restart themselves. This changes no configuration fields or archive formats and does not guarantee recovery from a persistent GPU fault.

The optional `yolo.iou` field accepts `0` through `1`; `yolo.tracker` accepts `botsort.yaml` or `bytetrack.yaml`. Omission (or null) keeps the SDK defaults, and the tracker option is used only when `tracking` is enabled. Configuration schemas include these additive fields; existing documents require no migration. Internal boxes now retain optional tracker IDs for live observations without changing archive metadata or event qualification. Tracker IDs are not persistent object identities.

The desktop onboarding runtime now defaults to its bundled native executable; NVIDIA presence no longer selects Docker or requires its installation. Explicit Docker selections remain supported. Python configuration and archive formats are unchanged. The launcher adds `--status-json`, a versioned operational status stream whose source identifiers are hashes rather than camera addresses. Deploy the web application and detector from the same complete application release so the detector understands that flag. Source callers may optionally inject the status reporter; existing callers need no change.

Automatic Windows ML provider discovery can fall back to CPU when the optional Windows acceleration service/library cannot be prepared. Explicit provider choices and invalid models remain visible failures. Hardware performance and provider-specific execution still require testing on the supported Windows machines.

Windows ML startup no longer opens a runtime installation dialog from the background detector. Provider preparation reports its stage and requests cancellation when the SDK's two-minute wait expires. Automatic selection skips individual preparation or DLL registration failures, preserving other registered providers; if all attempts fail it uses the CPU and reports the fallback. Explicit provider requests prepare only that provider and retain the original failure. CI no longer bypasses Windows ML through environment variables; packaged Windows smoke tests now cover automatic startup as well as explicit CPU inference. Configuration and detection archives are unchanged.

Windows ML discovery/preparation now runs in a short-lived helper process, using the same executable's internal `--prepare-windows-ml` action. PyWinRT stays out of the inference process to avoid its documented conflict with TensorRT RTX registration. Already-ready providers skip preparation. Pending operations retain the SDK's two-minute wait; the parent additionally kills and reaps a helper that exceeds 150 seconds, including native SDK stalls. Helper diagnostics are copied into the detector log on completion or timeout. ONNX registers the returned DLL paths after the helper exits; a blocked registration still produces a diagnostic stack trace after 150 seconds without terminating inference. Automatic CPU fallback, explicit provider selection, model settings and archives remain unchanged. No configuration migration or extra user installation is required. Startup also records the OS build/version to distinguish Windows versions accurately.

Native `.pt` conversion now writes reusable ONNX artifacts under the runtime data folder's `models/prepared/`. Existing `.onnx` files beside old checkpoints are left unchanged; new conversion cache entries are derived from checkpoint contents and settings, so an unrelated or stale sidecar cannot be mistaken for a matching model. Updating the model or conversion contract generates another cache entry. No configuration migration is required.

The architecture-boundary cleanup narrows the internal ONNX setup API, separates archive publication from media writing and simplifies delivery error storage. User configuration, archive metadata and runtime dependencies are unchanged. Runtime-only source installation can use `uv sync --locked --extra default --no-dev`; contributors retain the development group for quality checks.

The architecture/quality-tooling update adds development dependencies and CI reports only. Run `uv sync --locked --extra default` in a checkout to install them. No application configuration, archive or runtime dependency migration is required. Mutation testing runs on Linux/macOS (or Windows through WSL); Windows development sync omits that tool.

1. Keep the current release executable/container available and copy config.json before upgrading.
2. Validate the existing configuration with the replacement's config-check command. Correct only the explicit validation errors; keep credentials private.
3. Run a recorded input into a separate data directory before switching live sources. Compare event grouping and configured delivery rules.
4. Stop the old detector before starting the replacement on the same output location. Do not run two detector versions against one live output directory.
5. If reverting, stop the replacement, restore the previous executable/container and saved configuration, and restart. Archive formats remain compatible; no destructive data migration is required.

## Commands

From the updated `detector/` source directory:

```sh
uv sync --locked --extra default
uv run --no-sync aidetector --config /path/to/saved-config.json --check-config
uv run --no-sync aidetector --config /path/to/recorded-input-config.json --data-dir /path/to/trial-output
```

For an executable, replace `uv run --no-sync aidetector` with the executable path. For Docker, configuration and output stay under the mounted `/data` directory. The existing `main` command remains an alias.

Use a copied configuration for the recorded-input trial: point it to a local recording and a local model, and select a disk exporter. Live VLMs and notification destinations should only be present when their actual requests are intended. Stop the trial with Ctrl+C or SIGTERM if needed.

Review `unvalidated/*/metadata.json` for `validation_error` when checking provider availability. A finite run returns exit status 1 after any event validation/delivery failure; configuration errors use 2. A graceful stop observes failures during draining as well.

## Verification limits

See [AUDIT.md](../docs/history/detector/AUDIT.md) for the exact local checks and results. Automated tests and distribution checks use local fake services; they do not establish model quality or production provider accuracy. Windows ML registration and NVIDIA/Jetson hardware execution require those target systems. Existing archives, live configuration, and research/model assets are not migrated or deleted.

## Combined application setup

Live analyzed pictures are opt-in for standalone detector runs through `--live-preview`; the combined application supplies the flag. They reuse existing analyzed frames and add only bounded temporary operational data under `live/`. Camera credentials are not included in frame records. No configuration or archive migration is required, and disabling the flag preserves ordinary detection behavior. See [LIVE_PREVIEW.md](LIVE_PREVIEW.md) for the shared-data and single-publisher assumptions.

Model preparation now reports download/conversion/loading stages and an explicit `preparation_failed` observation for expected download failures. The launcher preserves that retry guidance after exit and resets it for a new run. These additions do not change model files, configuration, event rules or archive formats.

Packaged executables now use their bundled certifi roots for verified HTTPS downloads instead of relying on certificate files from the build computer's Python installation. An explicit `SSL_CERT_FILE` remains supported. Model URL failures distinguish HTTP responses, certificate verification, DNS resolution and timeouts in both the dashboard and logs, without exposing URL credentials. Existing model caches and configuration remain valid; failed downloads can be retried after updating the app.

Normal detector runs now retain Python diagnostics in `<data directory>/logs/detector.log`, rotating at 2 MiB with five backups. Console output remains available; an unwritable log directory falls back to the console. Offline CLI actions do not create logs. Startup records runtime versions, HTTPS trust settings and an allowlisted configuration summary before hardware setup. Camera connections, events and failed batches use abbreviated IDs matching the existing launcher source keys. Input failures include frame metadata rather than pixels, and credential redaction applies to formatted messages and tracebacks. Configuration, archive formats, inference behavior and the launcher status protocol are unchanged.

The new complete application download owns detector startup from the browser; separately managed CLI and Compose installations keep their existing lifecycle. `--control-stdin` opts into graceful `stop`/EOF control from the parent application, including Windows. No stdin handling is added to ordinary runs. Data remains under the configured runtime directory. See the [application guide](../README.md) for download targets and data locations.

## Python 3.12 and JetPack 6 retirement — 2026-09-28

Python 3.10 and 3.11 are no longer supported by new detector versions. The minimum is Python 3.12; [`.python-version`](.python-version) pins the exact version used by uv for development, CI and native packaging. Run `uv sync --locked --extra default` from `detector/` to recreate an older development environment. Configuration, model presets and the detection archive contract are unchanged.

Desktop users receive the interpreter in the application update. The downloadable Windows CUDA payload now uses the same pin, generated into `runtime.json` at build time. Its environment identity already includes the Python version, so the first launch after this update creates a new environment. Existing cached environments remain available for rollback. Windows CUDA 12.8 dependency pins are retained; removing older Python support does not change the inference backend.

The container workflow no longer builds the separate JetPack 6 variant. Previously published images are not deleted or retagged, and the legacy `example/compose.jetson.yml` remains available for existing installations. Keep the existing image on a JetPack 6 host; do not point it at the generic `latest` image.

New Jetson work targets JetPack 7.2 and Python 3.12. A supported JetPack 7.2 detector image still needs validation on real Orin hardware. The current Ultralytics generic ARM64 image is not a verified replacement: its [Jetson guide](https://docs.ultralytics.com/guides/nvidia-jetson/) calls for separate Orin/JetPack 7.2 validation and documents that its bundled TensorRT does not support JetPack. Before migrating a farm installation, qualify model loading/export, GPU inference, multiple streams and restart on that hardware, and back up the mounted settings and recordings.
