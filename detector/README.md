# AI Detector: the detector

The Python detector reads cameras or recorded media, groups YOLO observations into events, optionally verifies them with a vision language model, and delivers them to disk, Telegram or HTTP endpoints.

Most people use it through the [complete application](../README.md). This guide is for running it by itself and for working on it. Read [MIGRATION.md](MIGRATION.md) before replacing an existing installation.

## Run it

Use [uv](https://docs.astral.sh/uv/), which selects the Python version pinned in [`.python-version`](.python-version). All commands run from `detector/`.

```sh
uv sync --locked --no-dev --extra default
uv run --no-sync aidetector --init-config   # writes config.json; edit it
uv run --no-sync aidetector --check-config
uv run --no-sync aidetector
```

Install exactly one runtime extra per environment. They share the `onnxruntime` import name, so never combine them or use `--all-extras`.

| Extra | Runtime |
| --- | --- |
| `default` | Apple GPU on macOS for `.pt` models; CPU Torch on Linux; standard ONNX Runtime |
| `nvidia` | PyTorch with CUDA and ONNX Runtime GPU; needs matching NVIDIA drivers |
| `windowsml` | Windows ML runtime and Windows App SDK bindings |

| Flag | Effect |
| --- | --- |
| `--init-config` | Writes a template; refuses to overwrite a file. A normal run never creates or repairs configuration. |
| `--check-config` | Validates fields, bounds and source syntax without loading models, opening sources or making requests. |
| `--config FILE --data-dir FOLDER` | Keeps runtime data apart from the program. Relative input and model paths resolve against the configuration's folder; the data folder defaults to it and holds `detections/`, `models/` and `logs/`. |
| `--live-preview` | Publishes analysed pictures for the web application, which must share the data folder. See the [protocol](LIVE_PREVIEW.md). |
| `--test-vlm FILE` | Checks a verifier connection with generated media, without starting detection. |
| `--control-stdin` | Stops gracefully on a line `stop` or on EOF from the parent. |
| `--log-level` | `WARNING` hides routine activity; `DEBUG` adds per-batch details. |

**Executables and Docker.** [Releases](https://github.com/ESchouten/ai-detector/releases) carry platform builds that take the same flags; `--version` reports the build and runtime type. The [container image](../README.md#docker) holds the detector together with the web application that starts it; `docker run --rm IMAGE python3 -m aidetector …` runs the detector by itself from `/data`. A package that passes its smoke test has not shown that every GPU provider works on every machine.

**Jetson.** The ARM64 image is for Orin and Thor with JetPack 7.2 and has not been checked on a board yet; JetPack 6 images are no longer built. See [Jetson](MIGRATION.md#jetson).

**Stopping and exit codes.** Ctrl+C or SIGTERM stops acquisition, flushes eligible events and drains accepted deliveries. Exit `0` is success or a graceful stop, `1` an application, verification or delivery failure, `2` a configuration error, and `75` an Apple GPU error that a supervisor may answer with a restart. The detector does not restart itself.

**Logs.** Console and `logs/detector.log` in the data folder, rotating at 2 MiB with five backups. Lines name detectors by position (`[detector-2-delivery]`) and cameras by a 12-character ID, never by address. Credentials are masked, also in tracebacks; images, prompts and request bodies are never logged.

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

All options are in [`config.schema.json`](../config/config.schema.json). Sources, verifier entries, model names and exporters accept one value or a list. Unknown fields, empty required lists, duplicate sources, negative durations and invalid confidence ranges fail validation.

### Input

| Setting | Default | Meaning |
| --- | --- | --- |
| `detection.source` | required | Local image or video, HTTP video, RTSP/HTTP stream, or a camera index as a string such as `"0"` |
| `detection.interval` | `0` | Minimum seconds between sampled frames; files use media time and are not paced |
| `detection.frame_retention` | `15` | Unread sampled frames kept per live source while inference is busy; the latest is evaluated, earlier ones give context |
| `detection.frames_width` | `1280` | Maximum input width; aspect ratio is kept and smaller frames are not upscaled |
| `pending_events` | `8` | Completed events waiting for verification and delivery per detector; a full queue applies backpressure |

- Detectors that name the **same live source string** share one camera connection and its decoded frames. Each keeps its own sampling, frame size, tracking and event rules.
- Use separate detectors for files and live streams. Files in one detector are processed in order, and each file's end closes its own event. Live captures reconnect after expected failures.

### Detection and events

| `yolo` setting | Default | Meaning |
| --- | --- | --- |
| `model` | required | Local `.pt`, `.onnx` or `.engine` file, stock Ultralytics weight name, or HTTP(S) model URL |
| `task` | `"detect"` | `"detect"` or `"segment"`; must match the model |
| `confidence` | `0` | Minimum score, or a class map such as `{"person": 0.8}`; a map selects only those classes |
| `imgsz` | `640` | Inference input size |
| `frames_min` | `3` | Matching observations an event needs; they need not be consecutive |
| `time_max` | `60` | Event duration limit, from the first matching observation |
| `timeout` | `5` | Inactivity limit since the last match; `0` disables it |
| `include_trailing_time` | `1` | Maximum trailing context after the last match |
| `cooldown` | `0` | Per-source cooldown after acceptance, in seconds or a class map |
| `tracking` | `false` | Persistent Ultralytics tracking |
| `tracker`, `iou` | unset | `"botsort.yaml"` or `"bytetrack.yaml"`, and the overlap threshold; unset keeps the SDK default |

- Standard names such as `yolo11n.pt` are downloaded by Ultralytics; model URLs are downloaded once into the cache. Prepared ONNX models and TensorRT engines are cached under `models/prepared/`, which can be deleted while detection is stopped. See [inference backends](ARCHITECTURE.md#inference-backends).
- An event may proceed when at least one detected class is outside its cooldown. Approved and deliberately unvalidated events consume cooldown; rejected and failed ones do not.
- Without `yolo`, each sampled frame goes straight to the verifier and the exporters, and disk files it under `unclassified` unless `directory` is set.

### Verification

`vlm` takes one entry or an ordered list. Only entries with a non-null `key` run; clearing the keys switches verification off and keeps prompts and models.

| Field | Default | Meaning |
| --- | --- | --- |
| `prompt` | required | The question |
| `model` | required with a key | A LiteLLM model name or an ordered list |
| `key` | `null` | Provider API key. `""` means an unauthenticated local service, without environment-key lookup |
| `url`, `headers` | unset | Provider endpoint and extra request headers |
| `strategy` | `"VIDEO"` | `"VIDEO"` sends the event clip, `"IMAGE"` the best cropped frame |
| `crop_padding` | `0.1` | Extra crop margin |
| `timeout`, `attempts` | `30`, `3` | Request timeout in seconds, and attempts per model for transient failures |

The answer must be exactly one Boolean field, `detected`; a valid negative answer is final. Transient failures retry, invalid answers and permanent errors move to the next model, and a media encoding failure moves to the next entry. Media sent for verification has no overlays.

The outcomes are **approved**, **rejected**, **unvalidated** (no verifier) and **failed** (no verifier could answer). A failed verification sends no notification; disk can keep it under `unvalidated` with `validation_error`.

### Delivery

Every exporter accepts `confidence`, `crop_padding` (`0.1`) and `export_rejected`, which defaults to true for disk and false for Telegram and webhooks. Destinations are attempted independently, without hidden retries.

**Disk.** `directory` is one category name under `detections/` (default: the best class); `strategy` is `"BEST"` or `"ALL"`, which also writes every event frame. An archive is `best.jpg`, `clean.jpg`, `video.mp4` and `metadata.json` under `detections/<category>/<approved|rejected|unvalidated>/<timestamp>/`. Files are published together and an existing event is never overwritten. `metadata.json` names the camera by its 12-character ID from the logs, never by its address. `identities` in `metadata.json` lists the [recognised cows](#cow-identity-experimental). The web application adds a person's `review` to `metadata.json`; the detector never writes it.

**Telegram.** Needs `token` and `chat`. `alert_every` (`1`) plays the sound on every Nth alert. `quiet` takes a `start` and `end` such as `"22:00"` and `"06:00"`, in the computer's local time: alerts in that period arrive without sound. Photos are limited to 10 MB and videos to 12 MB. Alerts carry 👍 and 👎 buttons tied to the event's `event_id`; the web application receives the reviews. The caption is the confidence, the duration and, on a third line, the names of the recognised cows.

**Webhook.** Needs `url`; defaults to `method: "POST"` and `data_type: "binary"` (form fields and files), with `base64` (JSON) and `none` as alternatives. `headers` adds headers, `token` becomes the `Authorization` value, `body` replaces the generated content, and `data_max` limits each attachment. Payloads carry `confidence`, `timestamp`, `duration`, `validated` and `identities`, the names of the recognised cows: a list in JSON, one form field per name otherwise.

| Field | Telegram | Webhook |
| --- | --- | --- |
| `include_image` (clean full frame) | `false` | `false` |
| `include_plot` (annotated full frame) | `false` | `false` |
| `include_crop` (annotated crop) | `false` | `true` |
| `include_video` | `true` | `false` |
| `video_width`, `video_crf` | `1280`, `28` | `1280`, `28` |
| `timeout` | `30` | `30` |

### Cow identity (experimental)

An optional, noncommercial trial; a detector without `identity` runs none of it. In the complete application, choose the Cow Identity preset and confirm photographs on **Herd** with a name or tag number. Live labels are suggestions, and the detector never adds its own predictions to the confirmed photographs.

The preset sets `identity.model` to `"herd"`: the detector learns the confirmed cows. It adapts two kinds of network to the herd's photographs, three that start from weights taught other farms' cattle (`identity.weights`) and the published MIEWid network, keeps the result in `identities/herd/` and learns again when the confirmed photographs change. On a GPU that takes ten to thirty minutes for a few thousand photographs, on a processor alone hours, and names are hidden meanwhile. A crop is then compared with the confirmed photographs as the learned networks describe them. It needs photographs of a cow from many different occasions, across days, cameras, daylight and night: fifty spread like that named most animals in the trial, and hundreds from one afternoon almost none. It also needs most of the herd confirmed, because an unconfirmed cow that resembles a confirmed one is the main source of wrong names. On two held-out hours of public barn video the names it showed were right 99% of the time and unknown cows were refused, but it named only half of the animals at night and missed its own target there. Since that test a cow is compared with a share of her photographs instead of a fixed two, so that the limits hold as photographs are added; replayed over the same video that names as many animals and no unknown one. The other models compare a crop with the confirmed photographs through a published encoder, need no learning, and named few animals in every measurement. The preset detects with the largest stock model, which finds cows lying behind cubicle rails that smaller ones miss, and is meant for a computer with a GPU. The [research record](../research/cow_identity/HERD_LEARNING.md) has the protocol, the results and the limits.

| `identity` setting | Default | Meaning |
| --- | --- | --- |
| `labels` | required | Classes whose boxes are individual animals |
| `model` | `"miewid-msv3"` | `"herd"` learns the confirmed cows; `"miewid-msv3"`, `"dinov2-small-224"` and `"dinov2-small-336"` are published encoders |
| `weights` | unset | For `"herd"`, and required then: the cattle weights learning starts from, a `.safetensors` file or its URL |
| `min_similarity`, `min_margin` | `0.65`, `0.1` | A crop proposes a cow when it is this similar to it and this far ahead of the next cow |
| `min_similarity_infrared` | unset | The similarity needed in a picture without colour, as a camera takes under infrared light at night, where coats show less and look-alikes are more alike; unset, `min_similarity` |
| `min_observations` | `3` | Consecutive samples of a track that must propose the same cow before its name is shown; a track the detector misses for a few seconds carries on |
| `hold` | `0` | Seconds a shown name survives samples that fall short but still resemble that cow most, while no other animal in view claims it |
| `sample_interval` | `1` | Seconds between samples of one track |
| `min_crop_size`, `max_overlap` | `64`, `0.2` | Smaller boxes, boxes at the picture's edge and boxes overlapping another by more than this share are no evidence |
| `review_interval` | `30` | Seconds between photographs of one track saved for review on **Herd** |

**Names on other detectors' events.** A detector that watches for behaviour, such as Cow Catcher, boxes a scene and knows no animal. Put a Cow Identity detector on the same camera, and the other detectors' events on that camera carry the names of the cows recognised inside their boxes: in `metadata.json`, in the Telegram caption, in the webhook payload and on **Recordings**. A cow counts when more than half of her box lay inside the event's box at the same moment, in most of the pictures in which she was recognised while the event lasted and in at least two. The names are in order of how far each cow was inside the box. The mounting box frames the cow that mounts, so she is named, and first; the cow underneath is half hidden and named only sometimes, and now and then a cow standing close behind is named too. An event that names nobody says only that no cow was recognised. In a [simulation on the barn videos](../research/cow_identity/HERD_LEARNING.md#names-on-another-rules-events) 14 of 10,113 events carried the name of a cow that was not there and 84 that of a real neighbour; real mounts with known cows have not been measured.

`identity.mode: "continuous"` is a separate experiment that follows anonymous animals on one live camera, without enrollment. It needs native MPS and the optional SDK:

```sh
uv sync --locked --no-dev --extra default --extra identity-continuous
```

This installs the [vendored Cutie SDK](vendor/cutie/README.md); model weights are downloaded and checked against pinned hashes. No preset enables it and the packaged applications do not include it; see [what it changes](MIGRATION.md#cow-identity-experimental). Development installs include the SDK for type checking; its real CPU contract test runs only with `AIDETECTOR_TEST_CUTIE_WEIGHTS` set to a local weights file.

### Runtime and health

- `onnx.provider` requests an installed execution provider; `onnx.winml` (`true`) registers Windows ML providers in Windows ML builds; `onnx.opset` (`20`) is used for model export.
- `health` takes a `url`, `method` (`GET`), `interval` (`60`), `timeout` (`5`), and optional `headers` and `body`. Failed pings are warnings.

## Working on it

```sh
uv sync --locked --extra default
uv run --no-sync pytest tests/test_reference_flow.py
```

That test follows one event from a temporary video to a real archive, with deterministic inference and verification. It needs no camera, model download, credentials or network, and is the best place to start reading. Follow the same event through the code:

1. [CLI](src/aidetector/cli.py) and [bootstrap](src/aidetector/bootstrap.py): arguments, configuration, and construction of sources, models and destinations.
2. [Runtime](src/aidetector/runtime.py): supervises processing and delivery, including failure and shutdown.
3. [Pipeline](src/aidetector/application/pipeline.py) and [event assembler](src/aidetector/domain/events.py): batches become observations and events.
4. [Delivery](src/aidetector/application/delivery.py): cooldown, verification and destinations.
5. [Disk archive](src/aidetector/adapters/exporters/disk.py): the files the web application reads.

[ARCHITECTURE.md](ARCHITECTURE.md) has the structure, the ownership rules and a table of [where each kind of change belongs](ARCHITECTURE.md#where-a-change-belongs). Read [AGENTS.md](AGENTS.md) before editing. A change to configuration or archive metadata needs regenerated schemas, and a note in [MIGRATION.md](MIGRATION.md) when someone upgrading must act.

Tests use temporary media, local stand-ins for external services and a generated ONNX graph, so they exercise real OpenCV, FFmpeg, Ultralytics and ONNX behaviour without downloads. Fake only external SDK and I/O boundaries. While editing, this selection imports no model runtime:

```sh
uv run --no-sync pytest -q tests/domain tests/application tests/test_configuration.py tests/test_schemas.py
```

### Development checks

```sh
uv run --no-sync ruff check src/aidetector tests tools
uv run --no-sync ruff format --check src/aidetector tests tools
uv run --no-sync ty check src/aidetector tools
uv run --no-sync lint-imports --no-cache
uv run --no-sync pytest
uv run --no-sync generate-schema --check
uv build
```

CI runs the full suite on Linux, Windows and macOS. [QUALITY.md](QUALITY.md) covers coverage and mutation testing, and [PERFORMANCE.md](PERFORMANCE.md) how to measure inference. VS Code has matching tasks: **Detector: check**, **Detector: core tests (fast)** and **Detector: debug reference flow**.

Executables are built with [distribution/build.py](../distribution/build.py). After building one, `uv run --no-sync python -m tests.support.smoke_package /path/to/executable` runs it through a model download, tracking, verification, archives, delivery and shutdown; `--model-format pt` also checks a Torch checkpoint.

## License

AGPL; see [LICENSE](LICENSE).
