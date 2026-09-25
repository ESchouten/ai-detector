# Detector migration

The rebuild covers the Python detector, its schemas, tests, and distributions. The Python rewrite preserved the web archive contract. The subsequent application setup work adds a combined web/native download and optional parent-controlled shutdown.

## Compatibility commitments

- Existing top-level `detectors`, `onnx`, and `health` configuration remains supported.
- Single values and lists remain accepted for sources, VLM configurations/models, and exporters.
- YOLO detection/segmentation, stable per-source tracking, class thresholds, collection windows, cooldowns, optional validation, disk, Telegram, webhook, and health pings remain available.
- Existing `detections/<category>/<stage>/<timestamp>/` archives remain readable. New archives keep best.jpg, clean.jpg, optional video.mp4, and metadata.json with the existing required fields.
- Runtime data is kept separate from installed source. Existing live config and detection archives are not modified by the rewrite or its tests.
- Docker, macOS, Windows CUDA, and Windows ML packaging remain supported; actual provider execution can only be verified on available hardware.

## Restore operational logging — 2026-09-25

The default `INFO` level again shows prediction/tracking timings and Ultralytics detection summaries, alongside startup, camera connection, event, validation, cooldown and export diagnostics. These messages were missing or debug-only after the rewrite. Camera success is reported only after decoding a frame; delivery success only after the exporter returns. Source URLs and configuration secrets stay out of the new diagnostics. `--log-level WARNING` suppresses routine activity. Model settings, event rules, configuration and the separate launcher status protocol are unchanged.

GPU bounding boxes now move to CPU memory once through Ultralytics before mapping their scalar values. This removes repeated MPS/CUDA synchronization without changing model output, confidence thresholds, coordinates or tracking IDs. Live inference still scores only the newest retained frame per source; older retained frames provide event context. The ordinary web preview continuously drains FFmpeg and retains only the latest complete JPEG while its browser is slow, avoiding upstream playback backlog. Neither change increases the number of frames submitted to inference.

## Live camera responsiveness and alert ownership — 2026-09-25

Live network capture uses one FFmpeg decoder thread to avoid frame-thread buffering and allows ten seconds for opening or reading a stream, replacing the overly short three-second timeout. Camera sharing, per-detector sampling, event windows, thresholds and delivery policy are unchanged. Analyzed previews now publish up to eight times per second while viewed, using the same bounded latest-frame transport. Packaged applications keep Matplotlib's font cache under `cache/matplotlib` in their data directory, avoiding a complete font scan on each launch.

The web alert editor again assigns recipients to detectors. It no longer splits multi-camera detector definitions to represent camera-level notification choices. Saving alert assignments changes only Telegram destinations; camera lists, models, event settings and other exporters remain intact. Existing configuration files are accepted without a schema migration or automatic merging of previously split detectors. Reading settings does not rewrite them.

## Linux desktop dependencies — 2026-09-25

The `default` extra now selects CPU builds of Torch and Torchvision on Linux. Native desktop installers no longer bundle unused CUDA libraries that pushed downloads beyond GitHub's release asset limit. The `nvidia` extra keeps GPU dependencies, and macOS keeps MPS support. uv now enforces the existing rule that `default`, `nvidia`, and `windowsml` are alternative environments. Models, configuration and detection archives are unchanged.

## Intentional corrections

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
- Standalone executables use Python 3.11 in the release workflow. Python 3.10 source installations select ONNX Runtime 1.23.x, which still provides their binary wheels.
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

The optional `yolo.iou` field accepts `0` through `1`; `yolo.tracker` accepts `botsort.yaml` or `bytetrack.yaml`. Omission (or null) keeps the SDK defaults, and the tracker option is used only when `tracking` is enabled. Configuration schemas include these additive fields; existing documents require no migration. Internal boxes now retain optional tracker IDs for live observations without changing archive metadata or event qualification. Tracker IDs are not persistent object identities.

The desktop onboarding runtime now defaults to its bundled native executable; NVIDIA presence no longer selects Docker or requires its installation. Explicit Docker selections remain supported. Python configuration and archive formats are unchanged. The launcher adds `--status-json`, a versioned operational status stream whose source identifiers are hashes rather than camera addresses. Deploy the web application and detector from the same complete application release so the detector understands that flag. Source callers may optionally inject the status reporter; existing callers need no change.

Automatic Windows ML provider discovery can fall back to CPU when the optional Windows acceleration service/library cannot be prepared. Explicit provider choices and invalid models remain visible failures. Hardware performance and provider-specific execution still require testing on the supported Windows machines.

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

The new complete application download owns detector startup from the browser; separately managed CLI and Compose installations keep their existing lifecycle. `--control-stdin` opts into graceful `stop`/EOF control from the parent application, including Windows. No stdin handling is added to ordinary runs. Data remains under the configured runtime directory. See the [application guide](../README.md) for download targets and data locations.
