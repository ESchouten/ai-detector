# Detector architecture

The detector watches video sources, groups object observations into events, optionally verifies an event with a vision language model, and archives or delivers the result.

It is a small hexagonal application. Event decisions are isolated from I/O, and dependencies point inward, following the [Clean Architecture dependency rule](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html). Application use cases (`DetectionPipeline.process`, `EventDelivery.deliver`) define the ports they need in `application/ports.py`; adapters implement them; bootstrap constructs everything explicitly. There is no injection framework and no interface per class: a protocol exists where there is a real I/O boundary, and event rules are ordinary functions and dataclasses.

## Dependency direction

```text
cli -> bootstrap -> runtime + concrete adapters
                       |
                       v
                  application -> domain
                       ^            ^
                       |            |
                    adapters -------+
```

| Package | Owns |
| --- | --- |
| `domain` | Frozen observation and event records, confidence rules, event windows, cooldown, verification outcomes. No I/O; time comes from the caller. |
| `application` | The order of inference, event assembly, verification and export, through narrow protocols. |
| `adapters` | Video input, YOLO, VLM requests, image and video encoding, event files, HTTP and Telegram, health pings, platform inference setup. |
| `configuration` | Pydantic input models, normalization, file loading and schema production. Models do not inspect hardware or read files at import. |
| `runtime` | Execution and supervision: one aggregation owner and one ordered delivery worker per detector, plus the optional health monitor. |
| `bootstrap` | Turning validated configuration into policies and concrete integrations, and their cleanup scopes. |
| `cli` | Arguments, logging scope, configuration errors, signals and exit status. Importing it is safe. |

`EventAssembler` and `Cooldown` hold deterministic state, so the domain is not stateless; it still performs no I/O. Image fields are annotated `NDArray[np.uint8]` under `TYPE_CHECKING`: the domain keeps useful types without loading NumPy or touching pixels. That annotation in `domain.models` is the only third-party dependency the core is allowed.

Adapters are grouped by responsibility:

```text
adapters/
├── exporters/     disk, archive_metadata, telegram, webhook
├── sources/       files, streams
├── inference/     model assets, ONNX providers, YOLO, prepared models and engines
├── media/         images, video, event attachments
├── health.py      periodic pings, supervised by runtime
├── diagnostics.py log formatting, redaction, rotation, configuration summaries
├── http.py        transport shared by exporters and health
├── live_preview.py, operational_status.py   desktop integration
└── vlm.py, vlm_check.py                     event verification and its connection check
```

Exporters, sources and inference never import one another, directly or indirectly; bootstrap connects them through application ports. Media and HTTP are shared. Archive metadata sits beside the disk exporter because it defines the public archive format. Package initializers do not re-export their children: import the module that owns an operation.

[`.importlinter`](.importlinter) declares the layers, the forbidden imports, adapter-group independence and acyclic siblings, including imports inside functions and type-checking-only imports. Two test files add what the contracts cannot see. `tests/test_architecture.py` checks that every source file is in the import graph; a folder without `__init__.py` would otherwise escape the rules. `tests/test_import_safety.py` imports the core in a child process and fails if that reads configuration, writes files, opens sockets, starts threads or processes, or loads an inference library. These checks establish structure, not that every responsibility is well placed; see [QUALITY.md](QUALITY.md).

## Where a change belongs

Tests mirror the `domain`, `application` and `adapters` packages.

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
| Cow names on another rule's events | [who lay inside](src/aidetector/domain/identity.py), [shared sightings](src/aidetector/adapters/named_sightings.py), [delivery](src/aidetector/application/delivery.py) | [inside an event](tests/domain/test_identity.py), [sightings per camera](tests/adapters/test_named_sightings.py), [named delivery](tests/application/test_delivery.py), [exports](tests/adapters/exporters/test_exporters.py) |
| Learning a herd from its confirmed photographs | [herd model](src/aidetector/adapters/inference/herd_model.py), [preparation](src/aidetector/adapters/inference/herd_gallery.py) | [learning, reloading and stopping](tests/adapters/inference/test_herd_model.py), [the hold](tests/domain/test_identity.py) |
| Capture continuity for identity and live pictures | [shared capture](src/aidetector/adapters/sources/streams.py), [continuity policy](src/aidetector/domain/identity_continuity.py) | [shared streams](tests/adapters/sources/test_shared_streams.py), [continuity](tests/domain/test_identity_continuity.py) |
| Continuous identity mode | [wrapper](src/aidetector/adapters/inference/continuous_identity.py), [Cutie runtime](src/aidetector/adapters/inference/cutie_runtime.py), [mask policy](src/aidetector/adapters/inference/identity_masks.py), [startup segmentation](src/aidetector/adapters/inference/identity_startup.py), [bootstrap](src/aidetector/bootstrap.py) | [configuration and startup](tests/test_continuous_application.py), [worker timing](tests/adapters/inference/test_continuous_identity.py), [Cutie lifecycle](tests/adapters/inference/test_cutie_runtime.py), [masks](tests/adapters/inference/test_identity_masks.py), [package integrity](tests/test_optional_sdk_package.py) |
| Anonymous evidence collection | [collector](src/aidetector/adapters/identity_profile_collector.py), [profiles](src/aidetector/adapters/identity_profiles.py) | [collection episodes](tests/adapters/test_identity_profile_collector.py) |
| Naming a live instance (not connected yet) | [instance assignments](src/aidetector/domain/live_identity.py), [command boundary](src/aidetector/adapters/identity_control.py) | [stale and conflicting names](tests/domain/test_live_identity.py), [worker queue and catalog contract](tests/adapters/test_identity_control.py) |
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

## Vocabulary

The detector has one model: turn footage from a source into a completed event, obtain its verification outcome, and apply cooldown and export policies. Domain, application and adapters are layers of that one model, not separate bounded contexts. There is no repository, aggregate base class or event bus, because nothing here needs one.

| Term | Meaning |
| --- | --- |
| Source | The configured identity of a camera, stream or file. Event windows and cooldowns are kept per source. |
| `Frame` | An acquired image and its source timestamp, before inference. |
| `Observation` | A frame with matching class scores and optional display boxes. It may be an unscored context frame. |
| Qualifying observation | An observation with a nonempty confidence map after class thresholds. Only these count toward `frames_min`. |
| `BoundingBox` | Image coordinates with an optional label, score and tracker ID. A cropped image is a media result, produced by an adapter. |
| Event window | The assembler's mutable, per-source collection while an event is active. |
| `DetectionEvent` | A completed, nonempty sequence of observations from one source in source-time order. Its best observation has the highest score; ties keep the first. |
| `ValidationResult` | Approved, rejected, unvalidated (no verifier) or failed (verifiers could not answer). |
| `EventResult` | An event, its verification outcome and its ID. Delivery outcomes belong to the application's `DeliveryReport`. |
| Cooldown | The interval since an accepted event's best observation, per source and class within one detector. |

Producers establish invariants once and consumers rely on them: sources and inference supply nonempty, ordered batches; images are `uint8` H×W×3 in BGR order; frozen records borrow arrays and score maps as read-only values. Consumers do not re-validate or copy.

The archive is a public projection for the web application. `EventMetadata` keeps its field names (`detections` is the number of observations including context; `crop` is the best observation's enclosing box) so that internal names can improve without migrating archives.

## Event rules

- An event begins with a qualifying observation and may include context that preceded it in the same batch. Boxes alone do not make a frame qualify.
- It closes at its maximum duration, after its inactivity timeout, at EOF, or when shutdown drains the detector. Trailing frames are kept only within the configured trailing time after the last qualifying observation.
- Buffered observations are consumed in timestamp order. Eligible trailing frames before a boundary stay with the closing event; the observation at the boundary starts the next window.
- State never crosses sources. Finite files use media time, so grouping does not depend on machine speed, and each file's EOF closes its own event. Live sources use capture time. `SourceBatch.advance_to` lets an idle live source expire its window; finite sources omit it.
- Without a YOLO model the pipeline emits one unscored event per source batch, holding its latest frame.
- Cooldown is checked before verification, on the delivery worker, so two events cannot both pass. At least one class of the best observation must be outside its cooldown. Approved and deliberately unvalidated results consume it for every class of that observation; rejection and failed verification do not.
- Consuming cooldown, a destination's eligibility and a successful delivery are three separate decisions. A failed exporter does not undo acceptance, which keeps the alert cadence when a destination is down.

## Verification and delivery

The four verification outcomes stay distinct everywhere. A configured verifier that fails must never turn into an ordinary unvalidated notification; disk may archive such an event under `unvalidated` with the error recorded. The disk adapter, not the domain, maps outcomes onto the public `approved`, `rejected` and `unvalidated` folders.

A verifier entry runs only when its `key` is not null; a non-null key requires a model. Python reads everything from `config.json` and never resolves the web application's shared connections: the web copies a connection into the detector's `vlm` settings when it saves. An explicitly empty key means an unauthenticated service and prevents environment-key lookup.

Fallback is finite and specific. Provider errors and invalid answers move to the next model; a media encoding failure skips that verifier entry so another strategy can run; exhausting all entries is failed verification. A valid negative answer is final. An unexpected `IndexError` or `ValueError` from the SDK reaches supervision rather than being reported as an unavailable verifier. The answer model has one Boolean field, `detected`, and is both the schema sent to the provider and the validator of its reply.

`EventDelivery` applies each destination's `ExportPolicy` before calling its exporter, so calling an adapter directly would bypass confidence and rejection filtering. Destinations are attempted independently. Expected failures are recorded; an unexpected one stops the worker after the others have been attempted.

Media is encoded once per requested variant and shared between destinations; the cache weakly references its event and is dropped with it. Video is written incrementally to temporary input rather than held as a second clip in memory. Disk events get unique directories and become visible only when media and metadata are complete. Raw pixels are never modified by overlays.

## Configuration boundary

`config.json` accepts a single value or a list for sources, verifiers and exporters, and the boundary normalizes them once. Reading or checking configuration never rewrites the file. Defaults are deterministic and do not depend on hardware.

Configuration owns source syntax and the finite-or-live distinction through a pure classifier; file existence and camera availability are runtime concerns. URLs for sources, webhooks and health use strict Pydantic validation and keep the validated string as written, including credentials. Disk categories are single directory names, enforced by the same constraint in Python and in the generated schema, which preserves the `detections/<category>/<stage>/<timestamp>/` layout the web reader depends on. Secrets are excluded from reprs and logs.

## Resource ownership

- **Runtime** owns the workers and their stop signal. Each detector has a processing thread (inference and event assembly) and a delivery thread (cooldown, verification, exports) joined by a bounded queue, which applies backpressure instead of retaining image sequences. Workers release a completed event before blocking for more work.
- **Bootstrap** owns one `StreamPool` per run. Every live subscription is registered before any capture opens; there is one capture thread per distinct source string. The pool closes before model teardown, also when startup fails part-way.
- **A `StreamSource`** is one detector's subscription, with its own sampling interval, width and bounded unread buffer. Subscribers that want the same width share one resized frame. A slow detector drops its own oldest frames; it cannot block acquisition or consume another detector's frames. Sharing is by exact source string within one process. File readers stay independent because they advance with each detector's media time.
- **Inference**: bootstrap enters `inference_runtime` once per run and `open_detector` once per YOLO model. Each context releases what it opened, including after a failure during startup. A detector's YOLO adapter owns its tracking state.
- **Health**: the adapter performs timed requests behind the `HealthMonitor` port and starts no thread of its own. Runtime runs it beside the workers and stops it when the last finite detector ends.

Shutdown attempts every registered stop before joining, so one failed stop cannot block the others, and each worker logs its own unexpected failure before it propagates. Expected live-source failures reconnect with an interruptible delay; invalid configuration and programming errors do not loop.

A `torch.AcceleratorError` during native MPS inference becomes `MpsInferenceError`, and the CLI exits with code 75 after draining. It never retries inside the damaged GPU context or switches to CPU; restarting belongs to whoever supervises the process (see [desktop integration](#desktop-integration)).

## Inference backends

Backend selection lives in the inference adapters; the domain and application never see it.

- **macOS**: `.pt` checkpoints run on native PyTorch MPS with FP16 when the device is available and no ONNX provider is configured. MPS batches from all detectors share one process-wide lock through prediction, result transfer and synchronization, because of [PyTorch's MPS threading races](https://github.com/pytorch/pytorch/issues/197805). CPU, ONNX and CUDA are not serialized by it.
- **Prepared ONNX models** (`prepared_models.py`): a `.pt` checkpoint is exported once into `models/prepared/`, keyed by checkpoint contents, task, dimensions, precision, opset and library versions, checked, and published atomically. The original checkpoint is never modified, and a failed export publishes nothing.
- **Windows NVIDIA**: the web application's process manager prepares a separate CUDA Python environment and starts the same CLI in it (see [distribution](../distribution/README.md#windows-nvidia-runtime)). On compute capability 8.0+ it adds `--prefer-tensorrt`.
- **Jetson container**: the ARM64 image starts the CLI with `--prefer-tensorrt` too. Without a CUDA device the preference is dropped with a warning and detection runs on the processor.
- **TensorRT engines** (`prepared_engines.py`, `tensorrt_worker.py`): monitoring starts with a cached engine or with CUDA, and missing engines are built one at a time in the background by a short-lived helper process. The engine key includes checkpoint, settings, GPU, driver and runtime versions. When the queue finishes with at least one new engine, one `models_ready` status record asks the desktop to restart monitoring once. Predictors are never swapped in a running process. Only this automatic optimization may fall back to CUDA; an engine the user supplied may not.
  - A failed build, or one cut off by a crash, leaves CUDA running and is tried again at a monitoring start at least 24 hours later. No timer retries it while monitoring runs. Pause and quit cancel a build without that delay.
  - Each attempt keeps `models/prepared/tensorrt/<identity>/build.log`; `failure.txt` beside it holds the reason.
  - The builder's 2 GiB workspace is scratch space, not a limit on GPU memory: weights and the running detectors come on top, and a build slows inference while it runs.
  - The helper watches a parent-owned stdin pipe with non-blocking reads, because a blocking read deadlocks native NumPy imports on Windows, and has a thirty-minute deadline.
- **Windows ML** (`windows_ml.py`): provider discovery and preparation run in a short-lived helper process, which keeps PyWinRT out of the inference process (a [documented conflict](https://ryzenai.docs.amd.com/en/latest/winml/troubleshooting.html) with TensorRT RTX registration). The helper has a 150-second deadline. Automatic selection skips providers that cannot be prepared and ends on CPU with a notice; an explicitly requested provider stays a visible failure.

Decisions about the libraries, with their reasons:

- Model downloads use Ultralytics' own downloader, with one attempt, because its curl fallback would expose URLs through subprocess output.
- The predictor is prepared once: asking an exported model for its class names otherwise creates a second, disposable ONNX session.
- Result mapping moves boxes to the CPU once (`Boxes.cpu()`); reading GPU scalars one by one synchronizes the device each time.
- `inference_runtime` temporarily wraps the ONNX session factory, because Ultralytics does not expose the Windows ML device and session options, and restores it on exit. Worker spinning is disabled so idle ONNX workers sleep.
- The adapter restores `pathlib.WindowsPath` and `PosixPath` after loading a checkpoint, because the SDK can leave them patched.
- After an FP16 export the graph is topologically sorted before validation: the CPU conversion can append casts after their consumers.

## Cow identity (experimental)

Optional: a detector without `identity` constructs none of this. The [trial guide](../research/cow_identity/README.md) has the file contract, the measurements and the limits.

- **Port.** `ObservationIdentifier` enriches only the newly inferred observation, before live publication and event assembly; retained context cannot advance agreement. `domain/identity.py` owns similarity and margin acceptance, conflicts and agreement over time. The gallery adapter owns crop quality, sampling and I/O.
- **Herd model.** `identity.model: "herd"` describes crops with networks taught from the herd's own photographs instead of a published encoder. `herd_gallery.prepare_herd` runs on the preparation executor: `herd_model.learn` adapts a pretrained network to the confirmed photographs by learning to sort them by cow, with a cosine-margin loss and every cow drawn equally often. Two kinds learn, because each is fooled by different strangers: three `CattleNetwork`s, DINOv2-small started from the cattle weights and taught in a different order each, and one `AnimalNetwork`, the published MIEWid at a 288-pixel input. The networks see no colour. They then describe every confirmed photograph, and networks and descriptions are kept under `identities/herd/` and reloaded for as long as the photographs and the starting weights are the same. The result is a `PreparedGallery` like the photograph gallery's, one reference vector per confirmed photograph and an encoder that describes a crop in their space, so one identifier and one set of domain rules serve both. A descriptor has one part per kind, and the gallery's `parts` keeps them apart: each kind scores a cow by its own most similar photographs, one in fifty of hers and at least two (`share` and `neighbours`, where the published encoders take the single best), and the cow's score is the mean of the two kinds. A share keeps the scores, and so the limits, where they are as a cow gains photographs. On an Apple GPU every learning step takes the shared inference lock, so detection runs between steps.
- **Hold.** `TrackAgreement` keeps a confirmed track's identity through samples that fall short of a match while they still resemble it most, for `hold` seconds after the last match. The identifier withholds that resemblance when the crop is unfit or another animal in view claims the identity. Holding never confirms a track. A track missing from an observation keeps its agreement until the identifier has not sampled it for the agreement's largest gap.
- **Names for other rules' events.** A rule without `identity` boxes behaviour, not animals. Bootstrap gives every identity rule's published observations to one [`NamedSightings`](src/aidetector/adapters/named_sightings.py), which keeps who was recognised where on each camera for ten minutes, as fractions of the picture because rules may analyse a camera at different sizes. `EventDelivery` asks it once per event, before validation, through `name_individuals`; `domain/identity.individuals_in_event` holds each sighting against the event's moment nearest in time, at most a second away, and names the individuals whose boxes lay mostly inside the event's for most of their sightings. `EventResult.identities` joins them with the identities on the event's own boxes, and the disk, Telegram and webhook exporters read that one list. An identity rule's own events are not named this way: their boxes already carry identities.
- **Night.** A picture whose pixels carry no colour was taken under infrared light. The identifier then asks for `min_similarity_infrared` instead of `min_similarity`: infrared hides the contrast between a red coat and a white one, so strangers resemble the herd more at night than by day.
- **Catalog.** The web application alone writes the confirmed catalog. Python publishes bounded, immutable sightings and reads the catalog by revision; suggestions never enroll themselves. A catalog edit clears the previous names at once, and a prepared gallery is published only if its catalog still matches.
- **Preparation.** The identifier is given a `prepare` function that turns a catalog into a `PreparedGallery`; bootstrap binds either the photograph gallery or the herd model to it. The encoder download, the starting weights and the embedding cache wait until two identities have reference photographs, so collecting works without them. Bootstrap shares one encoder per model. One background executor prepares models and galleries, at most one preparation per rule, and is joined before the shared cache closes. MPS encoders share YOLO's synchronization scope in `adapters/inference/device.py`.
- **Failures.** Expected catalog, image, download and cache I/O failures suspend enrichment, clear agreement and retry after 60 seconds; detection continues with the original observation and no invented identity. The rule-scoped `identity_*` status records report it. Encoder invariant errors and accelerator faults still reach worker supervision.
- **Capture continuity.** A live frame carries a `CaptureStamp`: capture epoch, decoded-frame sequence and monotonic read time. A reopened capture, changed picture geometry, a backward capture clock or a read gap above five seconds starts a new epoch, reported before its first frame. Identity state is per camera; an epoch change or a gap above `max(5 s, 3 × identity sampling interval)` clears it, and repeated or out-of-order frames are no evidence. The live preview rejects observations from an old epoch, and inference status carries the epoch of its input, so a late result cannot restore a camera's readiness. A stamp says the read was continuous, not that the camera's picture is fresh.
- **Continuous mode.** Bootstrap wraps the stateless YOLO detector in one `ContinuousIdentityDetector` with the pinned Cutie runtime, and opens no encoder or gallery for it. One live camera and one class per process, native MPS and a `.pt` model; a missing SDK or unsupported hardware fails at startup instead of choosing another tracker. It derives a 0.5-second, four-frame subscription from the shared `StreamPool` without changing the saved settings. Cutie processes every sample; YOLO and qualification run on alternate samples, and the detector omits a source for the steps between. Omission never hides a failed inference. A backlog, a gap of a second or more, or a new epoch clears the camera's state. `cutie_runtime` owns one model and one camera's segmentation core, with at most eight objects.
- **Anonymous evidence.** Qualified `TrackEvidence` goes to a bounded collector, not to the gallery. Three consecutive analysed samples make a collection episode. `identities/automatic/profiles.sqlite` keeps at most one fact per instance per ten seconds, sixteen candidates per profile, five hundred profiles, seven days and 256 MiB; a storage failure logs a notice and retries after sixty seconds while tracking continues. Only this subscription borrows `Frame.native_image`, at most 32 MiB, so evidence keeps the camera's resolution; inference, previews and events use the analysis pixels. A mask or a temporary track ID is not an identity: ear-number reading and recognition across visits are not implemented.
- **Not connected yet.** `domain/live_identity.py` and `adapters/identity_control.py` let a person name a temporary instance, guarded by generation, revision and capture epoch so that an old photograph cannot name a reused tracker slot. They are tested building blocks without a browser or CLI command.

## Desktop integration

The web application starts the detector and talks to it through four optional, separate channels. None of them reaches the domain.

- `--control-stdin`: a line `stop`, or EOF on the parent's pipe, requests the normal stop-and-drain path on every OS. Ordinary runs do not read stdin.
- `--status-json`: versioned records on stdout, prefixed `AIDETECTOR_STATUS `, carrying an event kind, a UTC time, a SHA-256 source key and the run-local `detector-N` and `disk-N` identities. They contain no camera address. `application/status.py` defines the kinds; `adapters/operational_status.py` writes them, limiting the frequent ones (frames, inference, processing, offline, waiting for delivery) to one per source and rule per second. The web application derives readiness from these records and their freshness, never from log text or from the process having started.
- `--live-preview`: the latest analyzed frame per rule, published only while someone is watching. See [LIVE_PREVIEW.md](LIVE_PREVIEW.md).
- Reviews: the delivery use case gives each `EventResult` a UUID shared by all destinations. Disk stores it as `event_id`; Telegram puts it in the review buttons. Receiving reviews and writing them into `metadata.json` belongs to the web application.

Managed monitoring is continuous: the web application restarts the detector after any unexpected exit. A standalone CLI run finishes at EOF and reports its exit status.

Logs are for people and are a separate concern: the diagnostics adapter writes the console and a rotating `logs/detector.log`, redacts credentials in messages and tracebacks, and names cameras by the first 12 characters of the same source key.
