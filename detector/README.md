# AI Detector

For the combined download with browser-based setup and automatic detector startup, see the [application quick start](../README.md). The instructions below also support separately managed detector installations.

The Python detector reads cameras or recorded media, groups YOLO observations into events, optionally verifies those events with a vision language model, and delivers them to disk, Telegram, or HTTP endpoints.

The web application reads the event archive through its documented directory and metadata contract. See [MIGRATION.md](MIGRATION.md) before replacing an existing installation and [ARCHITECTURE.md](ARCHITECTURE.md) for the code structure and ownership rules.

The `codex/cow-identity` branch also has an optional, noncommercial **cow identity trial**. Select the Cow identity preset in Settings, then open Herd to confirm clear photographs with a name or tag number. Multiple views of at least two cows are needed before matching starts. Live labels are suggestions; the system never adds its own predictions to the confirmed gallery. See [the trial guide and measured research](../research/cow_identity/README.md).

The separate experimental continuous-camera adapter can be installed from
`detector/` with `uv sync --locked --no-dev --extra default --extra identity-continuous`.
It uses the [vendored Cutie SDK](vendor/cutie/README.md) and pinned downloaded model
weights. Explicit `identity.mode="continuous"` enables anonymous collection on one
live camera using native MPS, with no enrollment requirement. See the
[experimental configuration and limits](MIGRATION.md#experimental-anonymous-continuous-mode--2026-10-03).
No default setup preset enables it. The normal runtime
installation does not include it. Development installs include the small SDK
for type checking; the real CPU contract test requires an explicit local
`AIDETECTOR_TEST_CUTIE_WEIGHTS` path and otherwise skips.

## Start contributing

Use Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). In this checkout, uv selects the version pinned in [`.python-version`](.python-version). From the repository root:

```sh
cd detector
uv sync --locked --extra default
uv run --no-sync pytest tests/test_reference_flow.py::test_video_to_validated_archive_uses_real_media_and_flushes_at_eof
```

This reference flow creates a temporary video, supplies deterministic inference and verification results, and checks the real JPEG/MP4 archive and its metadata. It needs no camera, model download, credentials, or external service. The development sync includes the test and quality tools; the [runtime installation](#run-from-source) below omits them. All subsequent Python commands in this guide run from `detector/`.

Read the application in this order, following one event:

1. [CLI](src/aidetector/cli.py): parse arguments, load configuration, and report the outcome.
2. [Bootstrap](src/aidetector/bootstrap.py): construct sources, models, policies, and destinations, and own their cleanup scopes.
3. [Runtime](src/aidetector/runtime.py): supervise processing and delivery, including failure and shutdown.
4. [Pipeline](src/aidetector/application/pipeline.py): turn source batches into observations and completed events.
5. [Event assembler](src/aidetector/domain/events.py): apply the event-window rules using source timestamps.
6. [Delivery](src/aidetector/application/delivery.py): apply cooldown, verify the event, and attempt eligible destinations.
7. [Disk archive](src/aidetector/adapters/exporters/disk.py) and [metadata](src/aidetector/adapters/exporters/archive_metadata.py): publish the files consumed by the web app.

Each configured detector has one processing thread that owns inference and event assembly, and one delivery thread that owns cooldown, verification, and exports. A bounded queue connects them. Live camera acquisition runs separately: one shared capture thread per exact source string, with independent sampling and bounded buffers for each detector. File readers remain independent. See [resource ownership](ARCHITECTURE.md#resource-ownership) for shutdown and lifetime details.

Tests mirror the `domain`, `application`, and `adapters` packages; tests spanning the application stay at the test root. Use this map to locate a change and its existing tests:

| Change | Implementation | Tests to start with |
| --- | --- | --- |
| Configuration fields or schema | [configuration](src/aidetector/configuration.py), [schema generation](src/aidetector/schema.py) | [configuration](tests/test_configuration.py), [schemas](tests/test_schemas.py) |
| Event timing | [event assembler](src/aidetector/domain/events.py) | [events](tests/domain/test_events.py) |
| Confidence, cooldown, or domain records | [policy](src/aidetector/domain/policy.py), [models](src/aidetector/domain/models.py) | [policy](tests/domain/test_policy.py), [models](tests/domain/test_models.py) |
| Inference/verification sequencing or delivery policy | [pipeline](src/aidetector/application/pipeline.py), [delivery](src/aidetector/application/delivery.py), [ports](src/aidetector/application/ports.py) | [pipeline](tests/application/test_pipeline.py), [delivery](tests/application/test_delivery.py) |
| Startup, shutdown, or worker supervision | [CLI](src/aidetector/cli.py), [bootstrap](src/aidetector/bootstrap.py), [runtime](src/aidetector/runtime.py) | [CLI](tests/test_cli.py), [runtime](tests/test_runtime.py) |
| MPS failure and managed process recovery | [YOLO adapter](src/aidetector/adapters/inference/yolo.py), [CLI exit codes](src/aidetector/cli.py), [process manager](../web/src/lib/server/managed-detector.ts) | [YOLO](tests/adapters/inference/test_yolo.py), [CLI](tests/test_cli.py), [process recovery](../web/tests/runtime-recovery.test.ts) |
| Support logs, safe configuration summaries, or log retention | [diagnostics](src/aidetector/adapters/diagnostics.py) | [diagnostics](tests/adapters/test_diagnostics.py), [CLI](tests/test_cli.py), [runtime](tests/test_runtime.py) |
| Launcher readiness and camera health | [status contract](src/aidetector/application/status.py), [JSON status writer](src/aidetector/adapters/operational_status.py) | [status protocol](tests/adapters/test_operational_status.py), [CLI integration](tests/test_cli.py), [shared capture](tests/adapters/sources/test_shared_streams.py) |
| Live analyzed pictures | [protocol](LIVE_PREVIEW.md), [live preview adapter](src/aidetector/adapters/live_preview.py), [pipeline](src/aidetector/application/pipeline.py) | [publisher lifecycle](tests/adapters/test_live_preview.py), [pipeline observations](tests/application/test_pipeline.py), [web bridge](../web/tests/live-preview.test.ts) |
| Camera sharing or file sampling | [streams](src/aidetector/adapters/sources/streams.py), [files](src/aidetector/adapters/sources/files.py) | [shared streams](tests/adapters/sources/test_shared_streams.py), [sources](tests/adapters/sources/test_sources.py), [file sampling](tests/adapters/sources/test_files.py) |
| Optional identity recognition | [identity policy](src/aidetector/domain/identity.py), [gallery matcher](src/aidetector/adapters/inference/identity_observations.py), [catalog](src/aidetector/adapters/identity_catalog.py) | [matching policy](tests/domain/test_identity.py), [gallery and cache](tests/adapters/inference/test_identity_observations.py), [shared files](tests/adapters/test_identity_catalog.py) |
| Experimental live-name confirmation building blocks | [instance assignments](src/aidetector/domain/live_identity.py), [exact-photo command boundary](src/aidetector/adapters/identity_control.py) | [stale and conflicting names](tests/domain/test_live_identity.py), [worker queue and catalog contract](tests/adapters/test_identity_control.py) |
| Optional continuous-camera SDK boundary | [Cutie runtime](src/aidetector/adapters/inference/cutie_runtime.py), [vendored SDK](vendor/cutie/README.md) | [CPU lifecycle](tests/adapters/inference/test_cutie_runtime.py), [package integrity](tests/test_optional_sdk_package.py) |
| Experimental anonymous continuous mode | [wrapper](src/aidetector/adapters/inference/continuous_identity.py), [bootstrap](src/aidetector/bootstrap.py), [bounded collection](src/aidetector/adapters/identity_profile_collector.py) | [configuration and startup](tests/test_continuous_application.py), [worker timing](tests/adapters/inference/test_continuous_identity.py), [collection episodes](tests/adapters/test_identity_profile_collector.py) |
| Experimental anonymous mask selection and geometry | [mask policy](src/aidetector/adapters/inference/identity_masks.py), [CPU startup segmentation](src/aidetector/adapters/inference/identity_startup.py) | [overlap and stable-ID boundaries](tests/adapters/inference/test_identity_masks.py), [cached research parity](../research/cow_identity/application_mask_parity.py), [actual startup parity](../research/cow_identity/application_startup_parity.py) |
| Experimental continuous identity quality gates | [continuity policy](src/aidetector/domain/identity_continuity.py) | [absorption, recovery and bounded history](tests/domain/test_identity_continuity.py), [recorded video replay](../research/cow_identity/application_continuity_parity.py) |
| YOLO, model assets, or ONNX providers | [inference adapters](src/aidetector/adapters/inference/) | [YOLO](tests/adapters/inference/test_yolo.py), [ONNX](tests/adapters/inference/test_onnx.py), [model assets](tests/adapters/inference/test_model_assets.py), [model loading](tests/adapters/inference/test_model_loading.py), [SDK lifetime](tests/adapters/inference/test_yolo_runtime.py) |
| Inference performance comparisons | [benchmark](tools/benchmark_inference.py), [measurement guide](PERFORMANCE.md) | [benchmark integration](tests/test_benchmark_inference.py), [shared resize](tests/adapters/sources/test_shared_streams.py) |
| Windows ML startup or provider downloads | [Windows ML helper](src/aidetector/adapters/inference/windows_ml.py), [ONNX registration](src/aidetector/adapters/inference/onnx.py) | [process isolation and timeouts](tests/adapters/inference/test_windows_ml.py), [provider selection and lifetime](tests/adapters/inference/test_onnx.py) |
| Downloaded Windows CUDA runtime | [distribution staging](../distribution/nvidia_runtime.py), [desktop preparation](../web/src/lib/server/nvidia-runtime.ts) | [payload and dependency checks](../distribution/test_nvidia_runtime.py), [process lifecycle](../web/tests/nvidia-runtime.test.ts), [Windows package installation](../web/tests/nvidia-runtime-installed.test.ts) |
| Model conversion or prepared cache | [export settings](src/aidetector/adapters/inference/export_settings.py), [prepared models](src/aidetector/adapters/inference/prepared_models.py) | [conversion/cache contracts](tests/adapters/inference/test_prepared_models.py), [model loading](tests/adapters/inference/test_model_loading.py), [real SDK export](tests/integration/test_model_export.py) |
| Automatic direct TensorRT | [GPU engine cache and background preparation](src/aidetector/adapters/inference/prepared_engines.py), [export worker](src/aidetector/adapters/inference/tensorrt_worker.py), [desktop preparation](../web/src/lib/server/nvidia-runtime.ts) | [preparation, concurrent monitoring, cancellation and fallback](tests/adapters/inference/test_prepared_engines.py), [runtime installation](../web/tests/nvidia-runtime.test.ts), [planned restart and shutdown](../web/tests/runtime-recovery.test.ts) |
| Cropping, annotations, or encoded media | [media adapters](src/aidetector/adapters/media/) | [media encoding](tests/adapters/media/test_encoding.py), [event media](tests/adapters/media/test_event_media.py) |
| VLM responses, fallback or connection check | [VLM adapter](src/aidetector/adapters/vlm.py), [connection check](src/aidetector/adapters/vlm_check.py) | [VLM validation](tests/adapters/test_vlm.py), [connection check](tests/adapters/test_vlm_check.py) |
| Archive format or publication | [disk](src/aidetector/adapters/exporters/disk.py), [metadata](src/aidetector/adapters/exporters/archive_metadata.py) | [disk](tests/adapters/exporters/test_disk.py), [reference flow](tests/test_reference_flow.py), [schemas](tests/test_schemas.py) |
| Telegram, webhooks, or health requests | [Telegram](src/aidetector/adapters/exporters/telegram.py), [webhook](src/aidetector/adapters/exporters/webhook.py), [health](src/aidetector/adapters/health.py) | [exporters](tests/adapters/exporters/test_exporters.py), [HTTP](tests/adapters/test_http.py), [health](tests/adapters/test_health.py) |

Read [AGENTS.md](AGENTS.md) before editing and [ARCHITECTURE.md](ARCHITECTURE.md) before changing a boundary. Follow the existing tests for the behavior you are changing, then run the [development checks](#development-checks). Public configuration or archive changes also require schema regeneration and a compatibility review in [MIGRATION.md](MIGRATION.md).

### Test feedback while editing

From `detector/`, run the domain, application and configuration tests without importing model runtimes:

```sh
uv run --no-sync pytest -q tests/domain tests/application tests/test_configuration.py tests/test_schemas.py
```

VS Code exposes the same selection as **Detector: core tests (fast)**. For adapter changes, use the focused tests in the table above. `uv run --no-sync pytest --ignore=tests/integration` skips the expensive real model exports and cold font-cache scan; `uv run --no-sync pytest tests/integration` runs those contracts explicitly. Run `uv run --no-sync pytest` before submitting: this includes real model export, media, HTTP and subprocess contracts. Native installers and compiled application lifecycle checks run separately in the distribution workflows. CI runs the full detector suite on Linux, Windows and macOS; branch coverage is collected on Linux only.

Test input variants belong at the cheapest layer that owns their behavior. Keep a real integration check for each distinct boundary, without repeating a full model export or process startup for every parameter. Fake only external SDK/I/O boundaries; preserve cleanup, failure and cancellation assertions.

### Debugging in VS Code

Open the repository root so VS Code loads the shared `.vscode` configuration. Install the recommended Python, Python Debugger, Ruff and ty extensions, then run **Tasks: Run Task → Detector: install dependencies** once. Use **Python: Select Interpreter** to select `detector/.venv`; a previously selected interpreter can override the workspace default.

Set a breakpoint in `DetectionPipeline.process` or `EventDelivery.deliver`, choose **Detector: debug reference flow** in Run and Debug, and press F5. The test generates its own video and runs two archive-category cases, so a breakpoint can be reached more than once. Step from a source batch through event assembly and delivery without cameras, downloaded weights or external services. See the [debug configuration](../.vscode/launch.json) and [VS Code Python debugging guide](https://code.visualstudio.com/docs/python/debugging).

**Tasks: Run Task → Detector: check** runs lint, formatting, types, schemas and the full test suite, which includes architecture checks. Individual tasks run one check or the reference flow. The Testing sidebar uses the same detector environment and `tests/` directory. Coverage, mutation runs and distribution builds remain separate [development checks](#development-checks).

## Run from source

Use Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). In this checkout, uv selects the version pinned in [`.python-version`](.python-version). From `detector/`:

```sh
uv sync --locked --no-dev --extra default
uv run --no-sync aidetector --init-config
# Edit config.json to select your input and model.
uv run --no-sync aidetector --check-config
uv run --no-sync aidetector
```

`main` remains an alias for `aidetector`. `python -m aidetector` uses the same entrypoint.

The detector never creates or repairs configuration during a normal run. `--init-config` explicitly writes an offline template and refuses to overwrite an existing file. `--check-config` validates JSON, fields, bounds, supported source syntax, and compatible source groups without loading models, opening sources, or making requests. Source availability, model class names, and provider compatibility are checked when starting detection.

Use explicit locations to keep installed code separate from runtime data:

```sh
uv run --no-sync aidetector --config /path/to/config.json --data-dir /path/to/runtime
```

Relative input and model paths resolve against the configuration directory. The data directory defaults to that directory and contains `detections/` and downloaded `models/`. No process-wide working-directory change is required.

Add `--live-preview` to publish live analyzed pictures for the web application. The combined application supplies this flag automatically. Standalone detector and web processes must share the data directory; pictures are encoded only while someone is viewing that camera. The [live preview protocol](LIVE_PREVIEW.md) explains freshness, resource limits and troubleshooting. Preview pictures do not imply that a recording or alert was delivered.

Standard names such as `yolo11n.pt` use Ultralytics' automatic model download. HTTP(S) model URLs also use Ultralytics' downloader, with separate cache directories for distinct URLs. Completed downloads are reused; failed or partial downloads are not published into the cache. The application has no custom HTTP transfer loop. URL downloads use one SDK attempt and its network timeout behavior; restart after correcting an unavailable URL or connection.

On macOS, `.pt` models use native PyTorch MPS with FP16 when Torch reports an available MPS device. No ONNX conversion is needed for that route. MPS batches take turns across detectors to avoid concurrent access to PyTorch's shared Metal backend; camera capture and event delivery continue independently. If MPS is unavailable, the existing ONNX route remains available. Set `onnx.provider` explicitly to select an ONNX provider instead; `.onnx` and `.engine` files keep their respective backends. Model loading or inference failures remain visible rather than silently switching backends.

Native ONNX conversions are reused from `models/prepared/` when the checkpoint contents, conversion settings and SDK versions are unchanged. Changing an image size, camera batch, precision, model or relevant library version produces a separate prepared model. Only successfully exported and checked graphs are published. This cache can be removed while detection is stopped; the next ONNX start prepares the models again.

The Windows application's automatic NVIDIA route first prepares working PyTorch/CUDA. On compute capability 8.0 and newer (including RTX 3000 and newer), it additionally downloads a pinned TensorRT runtime. These dependencies are installed before the detector process starts. Monitoring then uses cached engines or starts with CUDA while Ultralytics prepares missing FP16 engines one at a time in the background. After all build attempts finish, the desktop briefly pauses monitoring, drains accepted events and restarts once if any new engines are available. The restart loads those engines directly, without ONNX Runtime or Windows ML. Pause/quit cancels this restart. Failed-only or cached-only preparation does not restart monitoring; standalone runs use new engines on their next start. ONNX is an intermediate export format only. Existing `.onnx`/`.engine` files and explicit provider choices keep their configured route.

GPU-specific engines live in `models/prepared/tensorrt/`, separate from portable ONNX models. Their cache identity includes checkpoint contents, export settings, GPU, driver, CUDA and library versions. A separate process builds and checks dynamic batch/shape inference before publishing the engine. Each build has a thirty-minute limit and stops with monitoring; a failed optimization leaves CUDA running. The builder shares the GPU and can affect inference speed. Its scratch workspace is limited to 2 GiB, not its total memory use. Failed downloads/builds are deferred for 24 hours across restarts and retried on a subsequent start, not by a background scheduler. Changed dependencies/hardware select a new cache identity. No configuration migration or new setup option is required. FP16 conversion still needs representative GPU speed and detection-quality validation; see [PERFORMANCE.md](PERFORMANCE.md).

To diagnose preparation, open the web app's **Logs** tab and search for `TensorRT`. Each attempt also saves `models/prepared/tensorrt/<identity>/build.log`, with a launch marker, helper PID, import/export/test phases and SDK output; `failure.txt` holds the failure reason. The downloaded runtime enters the lightweight helper directly, enabling Python's fault handler before inference imports. While preparation runs, it records all Python thread stacks every 60 seconds and forwards them to the detector log. These periodic snapshots are diagnostic samples, not proof that compilation is stuck, and do not stop the build. They identify Python call sites but do not expose the internal state of a blocked GPU driver. On Windows these files are under `%LOCALAPPDATA%\AI Detector`, separate from the installation folder.

Select **one** runtime extra per environment:

| Extra | Intended runtime |
| --- | --- |
| `default` | Native MPS for macOS `.pt` models; CPU Torch on Linux and standard ONNX Runtime for exported models |
| `nvidia` | Native PyTorch/CUDA and ONNX Runtime GPU; requires compatible NVIDIA drivers/libraries |
| `windowsml` | Windows ML runtime and Windows App SDK bindings |

These packages share the `onnxruntime` import namespace. Do not combine the extras or use `--all-extras`. Native CUDA/TensorRT dependencies must match the target machine; the published platform builds configure their build type explicitly.

## Executables and Docker

[Releases](https://github.com/ESchouten/ai-detector/releases) contain the platform distributions. Run an executable from a terminal with the same flags shown above. Its default `config.json` location is beside the executable. `--version` reports the build reference and runtime type.

Docker runs the same module from `/data`. Mount your configuration and event data there. The repository's `example/compose.yml` demonstrates the detector and web UI together; replace the example's model/provider/notification settings before starting it. For a local image build, use `detector/` as the build context. The context excludes local recordings, weights, environments, and research outputs.

The release workflow builds Linux CUDA images, Windows ML/CUDA executables, and a macOS executable. Executable builds use the Python 3.12 patch release in [`.python-version`](.python-version) and run local ONNX and Torch-checkpoint smoke tests through inference, verification, and delivery. Local verification and hardware limitations are recorded in [AUDIT.md](../docs/history/detector/AUDIT.md). A successful package build does not establish that every GPU provider works on every target machine.

### Jetson installations

New detector versions require Python 3.12 and no longer publish JetPack 6 images. Existing JetPack 6 deployments can keep their previously published image and Compose configuration; those images receive no further updates. See [migration guidance](MIGRATION.md#python-312-and-jetpack-6-retirement--2026-09-28).

JetPack 7.2 provides a Python 3.12 environment, but the current generic NVIDIA ARM64 container is **not qualified for Orin / JetPack 7.2**. Ultralytics documents separate container validation and a TensorRT incompatibility in its current ARM64 image. Follow the [upstream Jetson guide](https://docs.ultralytics.com/guides/nvidia-jetson/) for platform requirements. A container build on an ARM64 CI runner does not establish Jetson GPU compatibility.

## Configuration

A minimal local detection/archive configuration:

```json
{
  "detectors": [
    {
      "detection": {"source": "video.mp4"},
      "yolo": {"model": "yolo11n.pt", "confidence": 0.5, "frames_min": 3},
      "exporters": {"disk": {}}
    }
  ]
}
```

Sources, VLM configurations/model names, and individual exporter definitions accept either a single value or a list. The boundary normalizes them once. Unknown fields, empty required lists, duplicate sources, negative durations, non-finite numbers, and invalid confidence ranges fail validation. Keep API keys and source URLs private.

Detectors using the **same live source string** in one application share a single camera connection and decoded frames. Matching requested widths also share resized pixels. They keep independent sampling intervals, frame sizes, retention limits, tracking and event rules. A slow detector cannot consume another detector's frames or create an unbounded backlog. Separate application processes still open separate connections; finite files retain independent readers. See [PERFORMANCE.md](PERFORMANCE.md) for interpreting timing logs and comparing inference engines without changing detection settings.

The complete machine-readable options are in [`config.schema.json`](../config/config.schema.json). The checked-in [template](../config/config.template.json) is valid and can also be generated with `--init-config`.

### Input and event collection

| Setting | Default | Meaning |
| --- | --- | --- |
| `detection.source` | required | Local image/video path, HTTP video, RTSP/HTTP stream, or a camera index as a string such as `"0"` |
| `detection.interval` | `0` | Minimum sampled-frame interval in seconds; finite files use media time and are not artificially paced |
| `detection.frame_retention` | `15` | Maximum unread sampled frames per live source while inference is busy; the latest frame is evaluated and earlier frames provide context |
| `detection.frames_width` | `1280` | Maximum input width; aspect ratio is preserved and smaller frames are not upscaled |
| `pending_events` | `8` | Completed events waiting for ordered verification/delivery per detector; a full queue applies backpressure |

Use separate detector definitions for finite files and live streams. Unsupported URL schemes, missing stream hosts, and HTTP image URLs fail configuration validation; images must be local files. Files in one definition are processed sequentially; each file's EOF closes its own event. Live captures reconnect after expected input failures. A programming error is surfaced to the supervisor.

| `yolo` setting | Default | Meaning |
| --- | --- | --- |
| `model` | required | Local `.pt`, `.onnx`, or `.engine` file, stock Ultralytics weight name, or HTTP(S) model URL |
| `task` | `"detect"` | `"detect"` or `"segment"`; must match the model |
| `confidence` | `0` | Minimum score, or a class map such as `{"person": 0.8, "car": 0.6}`; maps select only those classes |
| `tracking` | `false` | Persistent Ultralytics tracking with a stable slot for each source |
| `iou` | unset | Optional overlap threshold from `0` to `1` for Ultralytics non-maximum suppression; omission preserves the SDK default |
| `tracker` | unset | Optional `"botsort.yaml"` or `"bytetrack.yaml"` when tracking; omission preserves the SDK default |
| `frames_min` | `3` | Required matching observations in an event; context frames do not count, and matches need not be consecutive |
| `time_max` | `60` | Event duration limit measured from the first matching observation |
| `timeout` | `5` | Inactivity limit since the last matching observation; `0` disables this timeout |
| `include_trailing_time` | `1` | Maximum trailing context after the last match |
| `cooldown` | `0` | Per-source cooldown after acceptance, in seconds or a class map |
| `imgsz` | `640` | Inference input size |

An observation at the maximum-duration or inactivity boundary begins a new window. Buffered observations are processed in timestamp order, so eligible trailing frames before a boundary stay with the closing event. EOF and graceful shutdown flush eligible windows. File timestamps follow video position, so inference speed does not change grouping. The event's best frame is the one with the highest score.

Cooldown uses the best observation's source timestamp and class. An event may proceed when at least one detected class is eligible; omitted classes in a cooldown map are unrestricted. Accepted and deliberately unvalidated events consume cooldown. Rejection or unavailable validation does not. Cooldown is independent of an individual destination's delivery success.

Omit `yolo` to process each sampled frame directly through the optional verifier and exporters. Such frames have no object confidence; disk uses the `unclassified` category unless `directory` is configured.

### Optional verification

In the web app, add a named **AI connection** once, then select it in each detector. Connection credentials and model are shared; each detector keeps its own question and IMAGE/VIDEO choice. Presets provide optional starting questions and leave verification off until a connection is chosen. Existing manually configured verifiers keep working. For a standalone connection check, `ai-detector --test-vlm connection.json` uses generated media and the normal adapter, never camera footage.

`vlm` accepts one configuration or an ordered list. Only entries with a non-null `key` run. Clear keys to disable verification while retaining prompts, models and media settings. Python reads these values only from `config.json`, never `app.json`. Each configuration has:

| Field | Default | Meaning |
| --- | --- | --- |
| `prompt` | required | The detection question |
| `model` | required when a key is set | A LiteLLM model name or ordered list of names |
| `key` | `null` | Provider API key; null or omitted disables verification. Use `""` explicitly for an unauthenticated local service, without environment-key lookup |
| `url` | unset | Optional provider endpoint |
| `headers` | `{}` | Additional request headers, including custom authentication |
| `strategy` | `"VIDEO"` | `"IMAGE"` for the best cropped frame, or `"VIDEO"` for the event clip |
| `crop_padding` | `0.1` | Extra crop margin relative to the detected region |
| `timeout` | `30` | Provider request timeout in seconds |
| `attempts` | `3` | Maximum attempts per model for transient provider failures |

Choose a provider/model that supports the selected media and structured JSON responses. Verification media contains no detection overlays. The answer requires exactly one real Boolean field, `detected`. A valid negative answer is final. Transient failures retry with bounded backoff; invalid answers and permanent provider errors move to the next configured model. If media encoding fails, the next verifier configuration is tried, allowing an IMAGE verifier to follow an unavailable VIDEO verifier.

Outcomes are **approved**, **rejected**, **unvalidated** (no verifier), and **failed** (configured verifiers could not answer). A failed verification can be archived under `unvalidated` with `validation_error`; it does not send ordinary Telegram/webhook notifications.

### Delivery

All exporters support `confidence` (number or class map), `crop_padding` (`0.1`), and `export_rejected`. Disk defaults to exporting rejected events; Telegram and webhooks do not. Each destination is attempted independently. Expected delivery failures are logged and counted; unexpected failures stop the detector after other destinations are attempted.

Disk settings:

| Field | Default | Meaning |
| --- | --- | --- |
| `directory` | best class | Single category directory name inside `detections/`, such as `mounts`; paths, blank names, and dot-only names are rejected |
| `strategy` | `"BEST"` | `"BEST"` writes the best images and clip; `"ALL"` additionally writes every event frame |

An archive contains `best.jpg`, `clean.jpg`, `video.mp4`, and `metadata.json` under `detections/<category>/<approved|rejected|unvalidated>/<timestamp>/`. Metadata describes the complete event, including context. New folders use microseconds and collision handling; existing events are never overwritten. Files are prepared in the category's `.pending/` directory and published together. Existing archives remain readable; no data migration is needed.

Telegram requires `token` and `chat`. `alert_every` defaults to `1` and controls the notification sound every Nth attempted alert. `timeout` defaults to `30` seconds. The adapter sends text when no media is selected, the appropriate single-media method for one attachment, and an album for multiple attachments. The detector's encoder limits photos to 10 MB and videos to 12 MB. Alerts include 👍/👎 buttons linked by the same `event_id` saved on disk. Albums get a silent reply containing the buttons. The web application receives and saves reviews; standalone Python only sends alerts. See [recording review](../web/README.md) and the exporter tests for this contract.

Telegram and webhook media settings:

| Field | Telegram default | Webhook default |
| --- | --- | --- |
| `include_image` (clean full frame) | `false` | `false` |
| `include_plot` (annotated full frame) | `false` | `false` |
| `include_crop` (annotated crop) | `false` | `true` |
| `include_video` | `true` | `false` |
| `video_width` | `1280` | `1280` |
| `video_crf` | `28` | `28` |

`video_width: null` retains source width. CRF accepts 0–51; lower values produce larger, higher-quality files. Identical requested video variants are reused across destinations when their size limits permit.

Webhooks require `url` and default to `method: "POST"`, `timeout: 30`, and `data_type: "binary"`. Methods also support GET, PUT, PATCH, DELETE, and HEAD. `headers` adds request headers; `token` sets the `Authorization` value exactly as supplied. An explicit `body` overrides generated content.

Generated payloads include `confidence`, `timestamp`, `duration`, and `validated`. `binary` sends form fields and media files; `base64` sends JSON with encoded attachments; `none` sends no generated body. `data_max` limits each encoded attachment, not the total request or base64 expansion. An impossible limit is a delivery error. Requests have no hidden application-level delivery retry.

### Runtime and health

`onnx.provider` optionally requests a specific installed execution provider. `onnx.winml` defaults to `true` for provider registration in Windows ML builds; it is ignored for other builds. `onnx.opset` defaults to `20` for model export. Provider setup and compatibility hooks are scoped to the application lifetime. Installed SDK files are never deleted or modified.

Windows ML startup runs without installation dialogs. SDK discovery and downloads use a short-lived helper so PyWinRT cannot interfere with TensorRT RTX registration. Logs and dashboard status identify hardware preparation; each provider has up to two minutes to become ready, with a 150-second deadline for the complete helper. A stalled helper is stopped and its diagnostics are retained. In automatic mode, an unavailable provider is logged and skipped so other providers can still run. If none can be prepared, detection continues on the CPU with a notice. An explicitly selected provider remains a visible failure when unavailable. CI exercises the same startup path as installed applications.

`health` accepts an HTTP `url`, `method` (`GET`), `interval` (`60` seconds), `timeout` (`5` seconds), optional `headers`, and optional raw `body`. Expected request failures are warnings. An unexpected health-worker error stops processing and reaches the caller. Health pings stop when finite inputs end.

Ctrl+C or SIGTERM stops acquisition, flushes eligible events, and drains accepted delivery work. Shutdown can wait for in-flight requests and the bounded delivery queue. CLI exit codes: `0` for success/graceful shutdown, `1` for application or event-delivery/verification failure, and `2` for configuration errors. The application does not conceal failures with an endless restart loop; use a service manager if automatic process restart is desired.

Processing and delivery logs identify detectors by their one-based configuration order: `[detector-2-processing]` and `[detector-2-delivery]` refer to the second entry in `detectors`. Destination names such as `webhook-1` are local to that detector. Startup, shared capture and health logs retain their own thread identities; camera URLs are not used as detector labels.

The default `INFO` level includes the app, Python, OS and installed library versions, selected inference settings and HTTPS certificate location. Before hardware setup, each detector logs an explicit configuration summary: source IDs and hosts, sampling and frame retention, model identity, class thresholds, tracking, event rules, verification models, and destination policies. It also records model downloads and cache hits, conversion settings and timing, camera connections and reconnect attempts, inference timing, completed events, validation outcomes and exports. Camera IDs are the first 12 characters of the launcher's `sourceKey`, so shared captures, detector configuration and events can be matched without credentials.

Python logs are written both to the console and to `logs/detector.log` under the runtime data directory. The file persists across starts and rotates at 2 MiB with five backups (about 12 MiB total for ordinary log records). This preserves diagnostics after the web dashboard's short in-memory log tail has rolled over. If a log file cannot be opened, the console reports that failure and monitoring can still start. `--help`, `--version`, `--init-config` and `--check-config` do not create log files. Native library writes directly to stdout/stderr remain in the launcher/terminal output rather than the Python log file.

`--log-level WARNING` hides routine activity; `--log-level DEBUG` also records batch source IDs, retained-frame counts, timestamps, shapes and dtypes. A failed processing batch records that metadata at `ERROR` even at the default log level, followed by the traceback. Images, raw configuration, verification prompts, request bodies and headers are not included in configuration summaries. Console and file formatters remove URL credentials, paths and query strings and mask configured API keys, bot tokens and authorization header values, including in tracebacks. Human logs remain independent of the `--status-json` protocol.

## Comparing CPU and GPU load

For a useful Windows ML versus CUDA comparison, use the same model, camera streams, `detection.interval`, `imgsz` and open live previews. Compare steady-state detector process CPU usage and processed frames per second after model preparation. Total system CPU and allocated GPU memory alone do not measure inference efficiency.

ONNX startup logs report the actual session providers, the image tensor processing device and I/O binding. Windows ML can execute the model on NVIDIA while Ultralytics prepares tensors and processes results on the CPU. ONNX worker spinning is disabled so waiting workers can sleep. A listed CPU fallback provider does not by itself prove expensive model operations run on the CPU; use ONNX Runtime profiling to check their placement. Native CUDA keeps tensor operations on the GPU, while camera decoding/resizing still involves CPU work.

## Development checks

```sh
uv sync --locked --extra default
uv run --no-sync ruff check src/aidetector tests tools
uv run --no-sync ruff format --check src/aidetector tests tools
uv run --no-sync ty check src/aidetector tools
uv run --no-sync lint-imports --no-cache
uv run --no-sync coverage erase
uv run --no-sync coverage run -m pytest
uv run --no-sync coverage combine
uv run --no-sync coverage report
uv run --no-sync generate-schema --check
uv build
```

For a quick test run without measurement, use `uv run --no-sync pytest`. From a Git checkout, compare the working tree with a revision using `uv run --no-sync python tools/quality_report.py --base HEAD`. This writes `.reports/quality.md` and `.reports/quality.json`, including untracked Python source. Use a branch or commit instead of `HEAD` to compare a larger change.

On Linux/macOS, run targeted domain mutation tests with `uv run --no-sync mutmut run --max-children 4`, inspect `uv run --no-sync mutmut results`, and export JSON with `uv run --no-sync mutmut export-cicd-stats`. Windows users can run these in WSL. Mutation testing creates its working copies under ignored `mutants/`.

See [QUALITY.md](QUALITY.md) for report interpretation, architectural constraints and mutation-test limits. CI enforces lint/type/import contracts, publishes complexity/dependency changes and coverage as `detector-quality`, and runs domain mutation tests in a separate Ubuntu job with a `detector-mutations` artifact. Survivors are reported for review; failed or incomplete mutation runs fail the job. [REVIEW.md](../docs/history/detector/REVIEW.md) records the maintainability review and the resulting changes.

Regenerate committed schemas with `uv run --no-sync generate-schema` when changing their models. Tests use temporary local media, fake external transports, and a generated ONNX graph. They exercise real OpenCV/FFmpeg/Ultralytics/ONNX behavior without downloading model weights or contacting notification/AI services. Import-safety probes install their guards inside isolated subprocesses; separate negative cases verify that the guards detect prohibited behavior.

After building an executable, run `uv run --no-sync python -m tests.support.smoke_package /path/to/executable`. This checks a generated ONNX model downloaded from a local HTTPS server through Ultralytics, two-source tracking, structured verification through a local fake API, JPEG/MP4 archives, HTTPS delivery, and EOF shutdown. Repeat with `--model-format pt` to check a generated, untrained Torch checkpoint through download, loading and export. Both checks use temporary local assets and a test CA passed only to the child process; no external weights are downloaded or system certificates installed. A `--version` check alone does not load the inference or provider libraries.

Native application builds, development and CI use the Python version in [`.python-version`](.python-version). The Windows CUDA payload receives that same version during staging. Use this pin when reproducing executable builds; support for newer Python versions in source installations does not establish compatibility with every frozen build. The [combined application workflow](../.github/workflows/application.yml) calls [distribution/build.py](../distribution/build.py) for packaging. Individual detector executables can still be built locally with its `detector` command. The [container workflow](../.github/workflows/containers.yml) publishes amd64/arm64 images; `detector/v*` tags no longer publish separate native downloads.

## License

AGPL; see [LICENSE](LICENSE).

## Managed application shutdown

The bundled web application starts the detector with `--control-stdin`. A line containing `stop`, or EOF when the parent closes its pipe, requests graceful shutdown on every supported OS. Accepted events drain before exit, and export/validation failures retain their nonzero exit status. Ordinary CLI runs do not monitor stdin. Configuration checking remains offline and does not start the control thread.
