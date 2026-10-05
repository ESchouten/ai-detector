# AI Detector: the detector

The Python detector reads cameras or recorded media, groups YOLO observations into events, optionally verifies them with a vision language model, and delivers them to disk, Telegram or HTTP endpoints. Most people use it through the [complete application](../README.md); this guide is for running it separately and for working on it.

See [ARCHITECTURE.md](ARCHITECTURE.md) for structure and ownership rules, and [MIGRATION.md](MIGRATION.md) before replacing an existing installation.

## Start contributing

Use [uv](https://docs.astral.sh/uv/); it selects the Python version pinned in [`.python-version`](.python-version). All commands in this guide run from `detector/`.

```sh
uv sync --locked --extra default
uv run --no-sync pytest tests/test_reference_flow.py::test_video_to_validated_archive_uses_real_media_and_flushes_at_eof
```

That test creates a temporary video, supplies deterministic inference and verification results, and checks the real JPEG and MP4 archive and its metadata. It needs no camera, model download, credentials or network.

Read the code in this order, following one event:

1. [CLI](src/aidetector/cli.py): arguments, configuration, exit status.
2. [Bootstrap](src/aidetector/bootstrap.py): constructs sources, models, policies and destinations, and owns their cleanup.
3. [Runtime](src/aidetector/runtime.py): supervises processing and delivery, including failure and shutdown.
4. [Pipeline](src/aidetector/application/pipeline.py): turns source batches into observations and completed events.
5. [Event assembler](src/aidetector/domain/events.py): the event-window rules.
6. [Delivery](src/aidetector/application/delivery.py): cooldown, verification, and the eligible destinations.
7. [Disk archive](src/aidetector/adapters/exporters/disk.py) and [metadata](src/aidetector/adapters/exporters/archive_metadata.py): the files the web application reads.

Each detector has one processing thread for inference and event assembly and one delivery thread for cooldown, verification and exports, joined by a bounded queue. Live cameras are read by one shared capture thread per source string. See [resource ownership](ARCHITECTURE.md#resource-ownership).

Tests mirror the `domain`, `application` and `adapters` packages. To find the code and tests for a change:

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

Read [AGENTS.md](AGENTS.md) before editing. A change to configuration or archive metadata also needs regenerated schemas (`uv run --no-sync generate-schema`) and, when someone upgrading must act, a note in [MIGRATION.md](MIGRATION.md).

### Test feedback while editing

```sh
uv run --no-sync pytest -q tests/domain tests/application tests/test_configuration.py tests/test_schemas.py
```

This selection imports no model runtime; VS Code offers it as **Detector: core tests (fast)**. `pytest --ignore=tests/integration` skips the expensive real model exports. Run plain `uv run --no-sync pytest` before submitting. CI runs the full suite on Linux, Windows and macOS.

Tests use temporary media, local stand-ins for external services and a generated ONNX graph, so they exercise real OpenCV, FFmpeg, Ultralytics and ONNX behavior without downloading weights or contacting anyone. Fake only external SDK and I/O boundaries, and keep the assertions about cleanup, failure and cancellation.

To step through an event in VS Code, open the repository root, run **Detector: install dependencies** once, select `detector/.venv` as interpreter, set a breakpoint in `DetectionPipeline.process` or `EventDelivery.deliver` and start **Detector: debug reference flow**.

## Run from source

```sh
uv sync --locked --no-dev --extra default
uv run --no-sync aidetector --init-config
# Edit config.json to select your input and model.
uv run --no-sync aidetector --check-config
uv run --no-sync aidetector
```

`python -m aidetector` and the `main` alias use the same entry point.

- A normal run never creates or repairs configuration. `--init-config` writes a template and refuses to overwrite a file. `--check-config` validates fields, bounds and source syntax without loading models, opening sources or making requests.
- `--config FILE --data-dir FOLDER` keeps installed code apart from runtime data. Relative input and model paths resolve against the configuration's folder. The data folder defaults to that folder and holds `detections/`, `models/` and `logs/`.
- `--live-preview` publishes analyzed pictures for the web application, which must share the data folder. See the [protocol](LIVE_PREVIEW.md).
- `--test-vlm FILE` checks a verifier connection with generated media, without starting detection.
- `--control-stdin` stops gracefully on a line `stop` or on EOF from the parent; the complete application uses it on every OS.
- `--log-level WARNING` hides routine activity; `DEBUG` adds per-batch details.

Standard names such as `yolo11n.pt` are downloaded by Ultralytics; HTTP(S) model URLs are downloaded once per URL into the cache. Which backend runs a model, and how prepared ONNX models and TensorRT engines are cached under `models/prepared/`, is described under [inference backends](ARCHITECTURE.md#inference-backends). That cache can be deleted while detection is stopped.

Install exactly one runtime extra per environment:

| Extra | Intended runtime |
| --- | --- |
| `default` | Native MPS for macOS `.pt` models; CPU Torch on Linux and standard ONNX Runtime for exported models |
| `nvidia` | Native PyTorch/CUDA and ONNX Runtime GPU; requires compatible NVIDIA drivers/libraries |
| `windowsml` | Windows ML runtime and Windows App SDK bindings |

They share the `onnxruntime` import name, so never combine them or use `--all-extras`.

## Executables and Docker

[Releases](https://github.com/ESchouten/ai-detector/releases) carry the platform builds. An executable takes the same flags; its default `config.json` is beside it, and `--version` reports the build and runtime type.

Docker runs the same module from `/data`; mount configuration and recordings there. [`example/compose.yml`](../example/compose.yml) runs the detector and the web interface together; replace its model, provider and notification settings first. For a local image, use `detector/` as build context.

A package that builds and passes its smoke test has not shown that every GPU provider works on every machine.

### Jetson installations

JetPack 6 images are no longer built, and the generic ARM64 image is not qualified for Orin and JetPack 7.2. See [Jetson](MIGRATION.md#jetson).

## Configuration

A minimal configuration that archives detections from a local file:

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

Sources, verifier entries, model names and exporter definitions accept one value or a list. Unknown fields, empty required lists, duplicate sources, negative durations and invalid confidence ranges fail validation. All options are in [`config.schema.json`](../config/config.schema.json); the [template](../config/config.template.json) is what `--init-config` writes.

Detectors that name the **same live source string** share one camera connection and its decoded frames within a process. They keep their own sampling, frame size, retention, tracking and event rules.

### Input and event collection

| Setting | Default | Meaning |
| --- | --- | --- |
| `detection.source` | required | Local image/video path, HTTP video, RTSP/HTTP stream, or a camera index as a string such as `"0"` |
| `detection.interval` | `0` | Minimum sampled-frame interval in seconds; finite files use media time and are not artificially paced |
| `detection.frame_retention` | `15` | Maximum unread sampled frames per live source while inference is busy; the latest frame is evaluated and earlier frames provide context |
| `detection.frames_width` | `1280` | Maximum input width; aspect ratio is preserved and smaller frames are not upscaled |
| `pending_events` | `8` | Completed events waiting for ordered verification/delivery per detector; a full queue applies backpressure |

Use separate detector definitions for finite files and live streams. Files in one definition are processed in order, and each file's end closes its own event. Live captures reconnect after expected input failures. Images must be local files.

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

An observation at the duration or inactivity boundary starts a new window. EOF and graceful shutdown flush eligible windows. An event may proceed when at least one detected class is outside its cooldown; classes omitted from a cooldown map are unrestricted. Approved and deliberately unvalidated events consume cooldown; rejection and failed verification do not.

Omit `yolo` to send each sampled frame straight to the optional verifier and the exporters. Such frames have no confidence; disk files them under `unclassified` unless `directory` is set.

### Optional verification

`vlm` accepts one entry or an ordered list. Only entries with a non-null `key` run; clear the keys to switch verification off while keeping prompts and models. In the web application an **AI connection** is saved once and copied into each detector that uses it.

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

Choose a model that supports the selected media and structured JSON answers. The answer must be exactly one Boolean field, `detected`; a valid negative answer is final. Transient failures retry with bounded backoff, invalid answers and permanent provider errors move to the next model, and a media encoding failure moves to the next entry, so an IMAGE verifier can follow a VIDEO one. Media sent for verification has no overlays.

The outcomes are **approved**, **rejected**, **unvalidated** (no verifier) and **failed** (no verifier could answer). A failed verification sends no ordinary notification; disk can keep it under `unvalidated` with `validation_error`.

### Delivery

Every exporter accepts `confidence` (a number or class map), `crop_padding` (`0.1`) and `export_rejected`, which defaults to true for disk and false for Telegram and webhooks. Destinations are attempted independently, without hidden retries.

Disk:

| Field | Default | Meaning |
| --- | --- | --- |
| `directory` | best class | Single category directory name inside `detections/`, such as `mounts`; paths, blank names, and dot-only names are rejected |
| `strategy` | `"BEST"` | `"BEST"` writes the best images and clip; `"ALL"` additionally writes every event frame |

An archive is `best.jpg`, `clean.jpg`, `video.mp4` and `metadata.json` under `detections/<category>/<approved|rejected|unvalidated>/<timestamp>/`. Files are prepared in the category's `.pending/` folder and published together, and an existing event is never overwritten. The web application adds a person's review to `metadata.json` as `review`; the detector never writes it.

Telegram needs `token` and `chat`. `alert_every` (`1`) plays the notification sound on every Nth alert; `timeout` is `30` seconds. Photos are limited to 10 MB and videos to 12 MB. Alerts carry 👍 and 👎 buttons tied to the event's `event_id`; the web application receives the reviews.

| Field | Telegram default | Webhook default |
| --- | --- | --- |
| `include_image` (clean full frame) | `false` | `false` |
| `include_plot` (annotated full frame) | `false` | `false` |
| `include_crop` (annotated crop) | `false` | `true` |
| `include_video` | `true` | `false` |
| `video_width` | `1280` | `1280` |
| `video_crf` | `28` | `28` |

`video_width: null` keeps the source width. CRF runs from 0 to 51; lower is larger and sharper.

Webhooks need `url` and default to `method: "POST"`, `timeout: 30` and `data_type: "binary"`. `headers` adds request headers; `token` becomes the `Authorization` value as given; an explicit `body` replaces the generated content. Generated payloads carry `confidence`, `timestamp`, `duration` and `validated`: `binary` sends form fields and files, `base64` sends JSON with encoded attachments, `none` sends no body. `data_max` limits each encoded attachment.

### Runtime and health

- `onnx.provider` requests a specific installed execution provider; `onnx.winml` (`true`) registers Windows ML providers in Windows ML builds; `onnx.opset` (`20`) is used for model export.
- `runtime` (`auto`, `native` or `docker`) tells the complete application how to start this detector. The detector accepts the setting and does not read it.
- `health` takes an HTTP `url`, `method` (`GET`), `interval` (`60` seconds), `timeout` (`5` seconds), optional `headers` and `body`. Failed pings are warnings.

Ctrl+C or SIGTERM stops acquisition, flushes eligible events and drains accepted deliveries. Exit codes: `0` for success or a graceful stop, `1` for an application, verification or delivery failure, `2` for a configuration error, and `75` after an Apple GPU error, which a supervisor may answer with a restart. The detector does not restart itself.

Logs go to the console and to `logs/detector.log` in the data folder, rotating at 2 MiB with five backups. Lines name detectors by their position in the configuration (`[detector-2-delivery]`) and cameras by a 12-character ID, never by address. Credentials in URLs, keys, tokens and authorization headers are masked, also in tracebacks. At startup each detector logs a summary of its settings; images, prompts and request bodies are never logged.

## Development checks

```sh
uv sync --locked --extra default
uv run --no-sync ruff check src/aidetector tests tools
uv run --no-sync ruff format --check src/aidetector tests tools
uv run --no-sync ty check src/aidetector tools
uv run --no-sync lint-imports --no-cache
uv run --no-sync pytest
uv run --no-sync generate-schema --check
uv build
```

VS Code's **Detector: check** runs the same. [QUALITY.md](QUALITY.md) covers coverage, the change report and mutation testing, and what each can and cannot tell you.

After building an executable, `uv run --no-sync python -m tests.support.smoke_package /path/to/executable` runs it through a generated ONNX model served over local HTTPS, two-source tracking, verification against a local stand-in, real archives, delivery and shutdown at EOF. Add `--model-format pt` to check loading and exporting a Torch checkpoint. Executables are built with [distribution/build.py](../distribution/build.py); see the [distribution guide](../distribution/README.md).

## License

AGPL; see [LICENSE](LICENSE).
