# Smallest useful continuous-camera identity integration

Planning note only. No production hook or frozen research implementation was changed to prepare this note. The longer joint-readout control is still pending. Current studies support investigating explicit within-camera confirmation, not promising durable appearance recognition after departure, restart or camera change.

The reviewed-reference control has now been encoded. Its fixed appearance comparison remains weak: the original60 versus reviewed39 references produced58 versus26 correct names out of1795 visible known observations, and24 versus42 out of1799. Neither reaches useful coverage. More variants of these same photos or another small fine-tune are not the next integration task.

## Use the existing detector pipeline

Add one concrete `ContinuousIdentityDetector` in `detector/src/aidetector/adapters/inference/continuous_identity.py`, implementing the existing `ObjectDetector.detect(frames)` interface. It composes the raw detector, SAM initialization and Cutie state. Return normal `Observation` objects with stable object IDs and optional identity evidence. Keep their `CaptureStamp`, source date and pixels intact.

Do **not** insert Cutie into `GalleryIdentifier` or silently expand `ObservationIdentifier`: that existing port explicitly preserves box geometry, while Cutie generates new mask-derived boxes and must process every tracking frame. The current `DetectionPipeline` already publishes returned observations and sends them through the normal event/status lifecycle; it should not need a second processing loop.

Bootstrap selects the concrete adapter for an explicit experimental continuous-camera mode, with its dependencies registered on the existing `ExitStack`. Keep the existing appearance mode separate while comparisons remain research. A single added mode field in `IdentityConfig`, represented in the generated schema and preset, is enough; do not expose research thresholds in the basic UI. The currently checked-in cow-identity preset still uses1Hz YOLO26m-seg/ByteTrack and is **not** the successful research detector or cadence, so switching only the Python identifier would not reproduce the evaluated method.

Each configured physical source has one worker-owned Cutie core and one temporal policy state. Initially reject duplicate continuous-identity rules for the same source rather than introducing shared mutable cores across detector workers. Network captures can continue to be shared through `StreamPool`. Model weights may be shared read-only; object memory cannot. Multiple cores multiply memory use, so the first supported budget should be one camera until an actual multi-camera timing/memory test passes.

## Keep the runtime small and faithful

Use one additional `cutie_runtime.py` adapter for the pinned SDK/model load, reviewed joint-readout patch, stable object/channel mapping, initialization and resource release. Extract the successful pure policy into one `domain/continuous_identity.py` module: largest-component geometry, probability/reciprocal confirmation, causal quarantine/recovery and explicit slot lifecycle. Do not import research runners or their file/protocol machinery in the application.

The processing cadence, raw-detector cadence, model weights and precision must match the finally selected joint control. In particular, anonymous births currently require raw same-frame proposals at2Hz; the older fixed-seed experiment only corroborated names at1Hz. Do not substitute one cadence while claiming another result. Use a monotonic per-source schedule and retain no inference backlog. A duplicate or nonincreasing capture sequence never advances Cutie. A dropped scheduled frame is recorded; a continuity gap invalidates the source rather than processing stale frames to catch up.

Use `CaptureStamp.epoch` as the primary reset boundary. The capture adapter already changes epochs for reconnect, changed geometry and long gaps, and clears retained source frames. Also detect gaps seen only by the identity worker, because an overloaded consumer can lose continuity while capture stays healthy. Reconnect, resume, frame-size change, process restart or unsupported metadata-free live input clears all names, pending confirmations, slot state and model memory. A same-epoch nonconsecutive sequence by itself is normal at sampled cadence; elapsed time matters, not raw sequence adjacency.

Retain the validated maximum of eight simultaneous slots initially. Stable object IDs and per-instance tokens are never tensor-channel positions and are never reassigned to a new animal. Retirement must remove memory, pending birth evidence, quarantine history and its name mapping together. A returning animal is anonymous, even if it resembles a catalog cow. Do not silently drop an extra animal or transfer an old name when the budget is full: surface a clear camera status and keep untracked detections anonymous. The existing retirement proof is short; an actual repeated entry/exit memory-bound test remains required.

## Exact-frame confirmation through existing transport

The current `LivePreview` already publishes the analyzed JPEG together with `runId`, source/rule, capture epoch and sequence, and boxes. This is the correct source for a confirmation view. Camera-card video comes from an independent feed and the overlay stream intentionally omits the JPEG; those pixels must **not** supply confirmation coordinates.

1. Publish an anonymous active-instance snapshot from the identity adapter. The backend retains its actual analyzed image, mask and slot generation in a bounded cache and issues an opaque snapshot ID. It is not reconstructed from a browser-supplied rectangle or JPEG.
2. In the existing Herd page, show that frozen picture and let the farmer choose an existing cow or enter a name. The action says that it names the animal being tracked in this camera. The catalog remains the sole store of permanent cow IDs/names/reference examples; no process-memory track association is persisted as a durable identity.
3. Extend the existing managed-process stdin protocol with one versioned JSON command alongside the unchanged `stop` line. Send `requestId`, process run ID, source key, epoch, snapshot ID, instance token and confirmed catalog ID/revision. The stdin reader validates/enqueues it; the detector worker applies it. Never invoke GPU work from the stdin thread.
4. Reuse structured stdout status for a matching acknowledgement. The web server waits for that bounded acknowledgement and reports accepted, stale or unavailable. Restart/EOF fails pending requests; a repeated request ID is idempotent within its run. A new generic RPC server, persistent command directory or separate daemon is unnecessary.
5. Accept only if the retained snapshot belongs to the current run/source/epoch and the same still-active instance generation. Any retirement, epoch change or unresolved/conflicted continuity since the displayed frame makes it stale. A photo saved as a catalog example can remain useful after it becomes stale, but must not automatically name whichever animal now occupies the old box. Show this distinction in the response.

Naming an already tracked anonymous instance does not require replaying an old mask into the current model. For **new object initialization**, only same-frame image/proposal/SAM pixels may enter the core: an old UI rectangle must never be applied to a newer live frame. Allow confirmation after continuity loss only from a newly issued snapshot. A farmer can correct a name; conflict with an already named active instance on the same camera must be explicit, never quietly duplicate the cow name.

The current catalog sightings do not carry epoch/run/instance tokens; their stored `track_id` is insufficient for live confirmation. Keep ordinary historical photo review working, but do not interpret its current `assign` action as a live-track command. A separate small `identity_control.py` transport adapter and `confirm-live` Herd action are enough to make that boundary explicit.

## Startup is still a separate blocking experiment

The strongest crowded runs started with six individually reviewed masks and two later anonymous objects. The current raw-proposal duplicate gate admits only4/8 animals at empty startup. Omitting initially visible anonymous animals was harmful in the earlier six-seed control, so a convenient first-screen implementation must not hide missing cows or assume unknown animals are harmless background.

Before choosing startup semantics, reuse the cached first-frame raw detector proposals and existing SAM masks to prepare a prediction-only candidate sheet: opaque candidate IDs, full source context and each actual foreground mask; no biological labels, publisher boxes or scoring overlays. Review “one complete visible animal / mixed or fragment / duplicate / uncertain” independently, then compare candidate coverage only after that selection is frozen. This can establish whether farmer review of proposed masks gives a workable initial set without another model run. It cannot demonstrate automatic startup, and duplicate groups cannot be collapsed by highest confidence alone without measuring removed adjacent cows.

If candidate review works, the first useful UI is a single camera's live Herd confirmation queue with unconfirmed cows remaining anonymous. Initial appearance matches may be shown only as explicitly experimental suggestions; they cannot replace confirmation. Empty-core multi-object enrollment, observed unknowns and later births must all be tested with the same bounded policy before declaring this an operational farmer workflow.

## Minimal existing hooks and acceptance checks

| Existing location | Small required change |
| --- | --- |
| `configuration.py`, generated schema and one experimental preset | Explicit continuous mode and the actually selected cadence/model; no new basic tuning controls. |
| `bootstrap.py` | Construct/close the concrete wrapper; prevent multiple ownership of a source; skip gallery preparation for this mode. |
| `cli.py` and managed-detector stdin/status handling | Typed confirm command/ack, bounded queue and run-scoped idempotence; preserve stop/EOF behavior. |
| `live_preview.py`, shared web frame schema | Retained snapshot/instance reference and evidence kind for current-track confirmation; never encode a confirmation as an appearance probability. |
| Existing Herd server action/page | Confirm a frozen analyzed frame, select/create a catalog cow, show stale/unavailable outcomes and current camera scope. |

Tests should cover real failure boundaries: process/source epoch change invalidates both names and in-flight commands; stale sequence does not advance the core; retirement followed by numeric channel reuse cannot inherit a name; late confirmation after quarantine/retirement is rejected; same request delivered twice has one effect; stop and EOF still terminate; one exact shared frame drives proposals/masks/preview; slot-budget exhaustion is visible; no viewer lease is needed for tracking itself. Reuse cached-replay parity against the selected policy, then run a real one-camera pause/reconnect/confirmation test. No additional abstract backend framework or implementation-mirroring test matrix is needed.

The bounded success claim is: **a farmer-confirmed cow can keep its name while a validated continuous camera track remains intact**. Automatic identity across visits or days remains a separate unsolved requirement, and the UI should say so plainly.
