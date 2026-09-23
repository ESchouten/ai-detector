# Detector SDK reuse assessment

Historical assessment: source paths, measurements and recommendations describe the recorded snapshot. Start with the [current contributor guide](../../../CONTRIBUTING.md) for the maintained implementation.

Reviewed on 2026-09-19. Scope at assessment: all 32 modules under `src/aidetector` (3,078 lines), their integration contracts, the dependency declarations, and the installed SDK implementations. The findings below preserve that assessment and its probes.

File and line references below describe that snapshot. The [navigation migration](../../../detector/MIGRATION.md#developer-navigation-cleanup--2026-09-22) and [adapter grouping](../../../detector/MIGRATION.md#adapter-grouping-and-configuration-names--2026-09-22) map the renamed modules; the [contributor guide](../../../detector/README.md#start-contributing) links to current source and tests.

Implemented on 2026-09-22: `draw_boxes` uses Ultralytics `Annotator`; validation passes `_Answer` directly to LiteLLM; HTTP destinations use strict Pydantic URL validation while preserving original strings; `_restore_path_classes` leaves checkpoint conversion to Ultralytics and restores both path classes afterward. The original recommendations below are no longer pending. Current verification and platform limits are in [AUDIT.md](AUDIT.md).

Three replacements are worth making now: delegate annotation drawing to Ultralytics, structured-response schema construction to LiteLLM, and HTTP URL validation to Pydantic. A fourth area, checkpoint path compatibility, contains redundant conversion but still needs cleanup around an upstream side effect. The larger capture, event, and encoding adapters have concrete responsibilities that the inspected SDK APIs do not replace.

The inspected environment uses Ultralytics 8.4.80, ONNX Runtime 1.27.0, Torch 2.12.1, LiteLLM 1.89.4, Pydantic 2.13.4, imageio-ffmpeg 0.6.0, and Requests 2.34.2. Recommendations below use those implementations; current online documentation can describe newer code.

## Recommended changes

### 1. Delegate box and label drawing to Ultralytics

Location: `src/aidetector/adapters/media.py`, `draw_boxes`.

The 37-line function implements rectangles, text measurement, label backgrounds, font sizing, and placement with OpenCV. Ultralytics already provides these operations through [`Annotator.box_label`](https://docs.ultralytics.com/reference/utils/plotting/#ultralytics.utils.plotting.Annotator.box_label).

Keep a small adapter that copies the input image, translates each domain `BoundingBox` into coordinates and label text, and calls the annotator. Keep the existing clipping and empty-region behavior if the input contract permits those boxes. The application can still choose its blue color and percentage labels. Let the SDK own text placement and drawing details. Its text sizing and antialiasing differ, so verify the resulting images visually rather than promising identical pixels.

Import `Annotator` only when there are boxes to draw. This avoids loading the inference SDK for configuration/schema operations or passthrough runs. Preserve the OpenCV drawing path; enabling the SDK's Unicode/PIL path can introduce font discovery or downloads and needs a separate decision.

Local probe: the real annotator drew both labeled and unlabeled boxes, retained dimensions and dtype, and left the original read-only array untouched. This establishes the replacement API's basic contract, not complete visual equivalence.

Do not put Ultralytics `Results` objects in the domain merely to call `Results.plot()`. That would retain SDK-specific state and make the event model depend on inference internals. `Annotator` can remain entirely within the existing media adapter.

### 2. Pass the response model directly to LiteLLM

Location: `src/aidetector/adapters/validation.py:38`, `_request_answer`.

The application builds an eight-line `json_schema` envelope around `_Answer.model_json_schema()`. LiteLLM accepts `response_format=_Answer` and constructs the strict schema itself. This is a documented part of its [structured-output API](https://docs.litellm.ai/docs/completion/json_mode).

Replace the envelope with that argument. Retain `_Answer`, its strict Boolean and extra-field rejection, and `model_validate_json` for the returned content. Empty choices, absent text, and invalid answers remain external integration failures; the SDK accepting a schema does not prove that every provider returns a valid answer.

A loopback HTTP probe exercised the actual LiteLLM request path. It generated the same strict schema and parsed a Boolean answer. Strings, numbers, and additional fields remained invalid. The generated schema name follows the Pydantic class name instead of the current `detection_result` literal; update request-shape fixtures accordingly. No commercial provider was contacted.

### 3. Use strict Pydantic HTTP URL validation

Location: `src/aidetector/configuration.py:170`, `HttpConfig.http_url`.

The current validator manually checks the scheme, hostname, and port after `urlsplit`. Parsing is not complete URL validation: it currently accepts `https://camera with spaces/` as an HTTP destination.

Use a reusable `TypeAdapter(AnyHttpUrl)` with `validate_python(value, strict=True)`. Pydantic provides the [HTTP URL type](https://docs.pydantic.dev/latest/api/networks/#pydantic.networks.AnyHttpUrl) and [TypeAdapter validation](https://docs.pydantic.dev/latest/api/type_adapter/#pydantic.type_adapter.TypeAdapter.validate_python). After validation, return the original string and translate validation failures to a static, credential-free message. This preserves signed queries, scheme case, explicit ports, and the existing string field/schema contract.

Strict mode matters. In local probes, ordinary URL parsing accepted and repaired `http:camera` and `http:/camera`; strict validation rejected both. It also rejected spaces in the hostname, invalid/out-of-range ports, missing hosts, malformed IPv6, and non-HTTP schemes. Valid localhost, IPv6, and signed URLs passed. Returning Pydantic's normalized URL would change some valid representations, so validate without replacing the original text.

This intentionally rejects some malformed destinations that currently pass the offline check. Add that correction to the migration notes when implemented. Keep `source_kind` separately: camera indices, RTSP URLs, supported media extensions, and finite/live grouping are application input policy.

### 4. Remove duplicate checkpoint conversion, retain restoration

Location: `src/aidetector/adapters/yolo.py:170`, `_checkpoint_paths`.

The application replaces `pathlib.WindowsPath` with `PosixPath` before loading/exporting a checkpoint. The installed Ultralytics `torch_safe_load` already performs cross-platform path conversion. Its [checkpoint-loading reference](https://docs.ultralytics.com/reference/nn/tasks/#ultralytics.nn.tasks.torch_safe_load) describes the load path.

However, deleting our context manager outright is unsafe with the inspected version. Ultralytics 8.4.80's `temporary_modules` assigns the replacement attributes but only removes module aliases on exit; it does not restore those attributes. A real local checkpoint containing a serialized Windows path failed under plain `torch.load`, loaded successfully through `YOLO`, and left `pathlib.WindowsPath` changed. Restoring the original class before ONNX export still allowed that export to succeed.

Reduce this code to preserving and restoring the original path classes; let Ultralytics perform the conversion. Preserve both `WindowsPath` and `PosixPath`, because its Windows branch changes the latter. Name/comment the remaining scope as cleanup for that SDK side effect. Test restoration on successful and failed loads, and remove it when a verified upstream version restores the attributes itself. The Windows branch was inspected in source, not executed on Windows.

## Candidates that are not direct replacements

| Current code | Available library capability | Assessment |
| --- | --- | --- |
| `adapters/validation.py:69`: retries and fallback | LiteLLM retries, retry policies, and model fallbacks | Generic transport retry is an eventual candidate. The inspected synchronous helper requires Tenacity, which is absent from this environment; calling it failed before invoking even a local function. Its default retry predicate/backoff also differs. Media-strategy fallback, invalid-answer handling, a negative answer ending verification, and diagnostic redaction remain application policy. Do not replace the entire validator with a Router. |
| `adapters/onnx.py:58`: Windows DLL discovery | `onnxruntime.preload_dlls` | There is partial overlap for CUDA runtime, cuFFT, and cuDNN discovery. The application already calls the SDK preloader on its CUDA ONNX path. Windows NVRTC, cuRAND, TensorRT, frozen-package layouts, and startup before early returns need separate verification. Narrow this only after testing the actual Windows CUDA/TensorRT distributions. |
| `adapters/video.py:68`: FFmpeg process ownership | `imageio_ffmpeg.write_frames` | The installed helper blocks while writing frames to stdin; its timeout applies to waiting for process completion during generator cleanup. It also does not check a nonzero exit status like the current adapter. The current staged-file input and `subprocess.run(timeout=120)` bound an entire encoding attempt. Replacing this wrapper would lose behavior or require another wrapper. Keep it. |
| `adapters/streams.py:136`: capture/reconnect loop | Ultralytics `LoadStreams` | The loader manages capture, but does not provide this application's one-source/multiple-detector subscriptions. Its constructor can fail when a camera starts offline, its buffers/stride have different semantics, and its batch reader waits for every source. The current pool provides independent sampling, unread retention, idle batches, and capture timeouts. Keep the pool and the small OpenCV capture boundary. |
| `adapters/files.py`: finite media reader | Ultralytics `LoadImagesAndVideos` | File loading overlaps, but media-time sampling, explicit per-source EOF, source identity, and shutdown are part of the detector contract. Adapting a different batch/stride protocol would not clearly simplify this 88-line reader. |
| `adapters/yolo.py:25`: in-memory stream adapter | SDK NumPy/list loaders | Ordinary image-list input does not preserve stream-mode per-camera tracker slots. Keep this narrow adapter and its real multi-source tracking tests. |
| `adapters/yolo.py:183`: explicit predictor setup | `YOLO.predict` and `YOLO.names` | The installed `names` property creates a temporary predictor for exported models and does not retain it. Removing setup would open another session at inference, or move class validation to the first frame. Keep the current explicit setup until the SDK exposes an equivalent public initialization path. |
| `adapters/onnx.py:233`: session hook | Ultralytics ONNX backend | The inspected backend constructs its own session with CPU/CUDA/CoreML selection and exposes no session-options/provider-device injection. Windows ML registration, device selection, and custom provider options cannot simply be deleted. Keep the scoped adapter; prefer an upstream injection API when available. |

Relevant upstream references: [LiteLLM retries/fallbacks](https://docs.litellm.ai/docs/completion/reliable_completions), [ONNX Runtime DLL preloading](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html#preload-dlls), [imageio-ffmpeg 0.6.0 writer source](https://github.com/imageio/imageio-ffmpeg/blob/v0.6.0/imageio_ffmpeg/_io.py), [Ultralytics source loaders](https://docs.ultralytics.com/reference/data/loaders/). The conclusions above also rely on the installed source and the application's tested contracts.

## Application behavior that should remain ours

- Event windows, minimum matching frames, trailing footage, EOF flushing, and per-source/class cooldowns.
- Per-class confidence thresholds and translating SDK results into application records. Ultralytics already owns preprocessing, inference, suppression, tracking, and model export.
- Cropping the union of detections to a preferred aspect ratio without cutting away the detected region. `save_one_box` has gain/pixel-padding/square options, not this complete contract.
- Selecting and encoding attachments to byte limits. OpenCV and FFmpeg already do the encoding; the application chooses quality/size attempts and reports an impossible limit.
- Reusing encodings across destinations without retaining completed events, and publishing complete archive directories atomically.
- Delivery policy, alert cadence, payload fields, and credential-free application errors. Requests already performs HTTP and multipart encoding; adding a bot or workflow framework for the small remaining adapters would introduce more machinery.
- URL-specific model cache locations and atomic publication. Ultralytics already performs the transfer and stock-model lookup after the preceding change.
- CLI arguments, JSON schema generation, bounded queues, worker supervision, and resource cleanup. These already use standard-library or installed-library primitives rather than implementing substitutes.

## Verification during the original assessment

The existing Python 3.12 suite passed: **267 tests**, including real inference/model export, local media/reference flows, source sharing, local HTTP integrations, and architecture checks. Ruff, formatting, source typing, and generated-schema checks passed. The two existing Torch ONNX-export deprecation warnings remain.

Separate temporary probes verified annotation behavior, a cross-platform checkpoint load and ONNX export, the SDK's lingering path mutation, LiteLLM's generated request body through a loopback server, strict response parsing, URL validation differences, and the unavailable optional retry helper. External network connections were blocked for the model/annotation/provider probe; documentation was read separately. These probes do not establish hardware or live-provider compatibility.

The assessment recommended implementing findings 1–3 at their existing boundaries, then narrowing finding 4 with restoration regression tests. Those changes are now complete; the implementation pass adds contract tests and distribution verification recorded in AUDIT.md. No executable was rebuilt during the original assessment. Native Windows, NVIDIA/Jetson, real cameras, and commercial providers were not exercised.
