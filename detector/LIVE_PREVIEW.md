# Live analyzed pictures

`aidetector --live-preview` enables an optional local file transport shared with the web application. Managed launches enable it automatically; standalone launches must opt in and share the same data directory with the web application. It creates no HTTP server and uses no extra camera connection.

`DetectionPipeline` calls its `PublishObservation` callback after successful inference, before event aggregation. The callback receives the latest analyzed observation, including its original image and bounding boxes. Snapshot rules publish their current image with empty boxes. It does not create an event, change event scores, or depend on whether an event meets recording or notification thresholds. Track IDs are optional, scoped to a tracking run, and have no identity meaning.

The live adapter owns one thread. Its callback only replaces the latest pending observation for each configured source/rule pair when a viewer is active. Encoding and filesystem work happen on the thread, at most eight times per second per pair. A slow encoder cannot accumulate a frame history or block inference. Image pixels follow the existing borrowed read-only observation contract.

## Version 1 files

All paths below are inside `DATA_DIR/live`. Source keys are SHA-256 hashes of the detector's resolved source string; filenames and messages never contain camera URLs or credentials.

* `session.json`: `{version: 1, runId, updatedAt, sourceEpochs}`. `sourceEpochs` maps configured source keys to the current capture epoch, or `null` while disconnected. It is optional when reading older files. A unique ID identifies each process run. The publisher replaces its heartbeat once per second and removes its own session on orderly shutdown.
* `leases/<sourceKey>.json`: `{version: 1, expiresAt}`. Expiry is Unix seconds. The web process shares one lease between viewers of a source, renews it every three seconds, and removes it when the final viewer disconnects. A lease expires after twelve seconds if the web process crashes. Python ignores invalid or expired leases.
* `frames/<sourceKey>.detector-<ordinal>.json`: `{version: 1, runId, sourceKey, ruleId, capturedAt, publishedAt, image, boxes}`. The image is `{width, height, jpeg}` with a base64 JPEG. Boxes contain pixel coordinates `x1, y1, x2, y2`, nullable `label`, `confidence`, and `trackId`. Live records also carry `capture: {epoch, sequence}` from the analyzed frame. This field is absent for metadata-free finite sources. Each record is written to a temporary sibling and atomically replaced, keeping image and boxes coherent.

Each rule/source pair has one retained record. Starting a publisher removes previous run records and its known temporary frame files. Preview failures are logged independently of event processing; a failed rule's encoding does not stop other rules from publishing.

## Web stream

`GET /cameras/live?camera=<stable-camera-id>` resolves each requested camera and every configured rule on the server, then streams same-origin SSE. Repeat the `camera` parameter for multiple cameras. Visible camera cards share one connection, preserving browser connection slots for video and navigation. The shared TypeScript contracts are in `web/src/lib/live-preview.ts`.

* `frame` contains the version 1 record plus the camera ID, current rule label and optional preset. Its image contains only width and height; JPEG bytes stay on the server. Boxes scale to the independently playing camera video, with letterboxing preserved. They represent the latest analyzed result, so moving objects can move beyond their boxes between inferences.
* `status` contains a waiting or unavailable message, usually with the affected camera ID, rule ID and label. It clears the corresponding boxes; an empty detection result also clears previous boxes for that rule.
* `heartbeat` contains `{}` when neither pictures nor statuses changed. The browser can distinguish an unchanged picture from a stalled connection.

The server accepts a frame only for the current session and matching source/rule. When the session declares a source epoch, the frame must carry that same epoch. A disconnected source clears its overlays even if an older frame was published recently. Older sessions without epoch metadata retain their existing age-based behavior. A session becomes unavailable after six seconds without a heartbeat. A frame becomes unavailable after the larger of fifteen seconds or three configured inference intervals plus five seconds. Freshness uses publication time; file footage may have historical capture timestamps. A changed run ID closes the stream so reconnecting resolves current configuration and labels. Slow consumers skip intermediate records instead of building an unbounded response queue.

The transport assumes one detector publisher and one web process share the data directory, as in managed installations and the supplied Compose configurations. The preview is an operational view, not a recording archive or proof that recording and alert delivery succeeded.

## Capture continuity

Before publishing the first frame of a reopened camera, changed native geometry, backward capture clock, or raw read gap above five seconds, capture reports an unthrottled `source_epoch` event. Disconnect reports are also unthrottled. Bootstrap sends source status synchronously to the preview before forwarding it to the launcher. The preview immediately invalidates that source’s queued observations, keeps other cameras intact, and checks the epoch both before JPEG encoding and after temporary-file writing. Only the final guarded rename holds the state lock; capture never waits for JPEG encoding or file serialization. Late worker output from a previous epoch cannot become a fresh-looking picture. Inference and snapshot-processing status records carry the analyzed capture epoch too. Once the launcher knows a camera epoch, results with a different or missing epoch cannot establish readiness or refresh processing activity. The status limiter retains only the last time/epoch per kind, source and rule, so an old result cannot suppress the first result from a new connection.

The session heartbeat communicates this bounded per-source state using the existing transport. Browser visibility can lag behind capture invalidation until the next heartbeat/poll, and an unusually slow encoder may delay that heartbeat until the existing stale-session limit applies. This patch does not add live confirmation or guarantee synchronization with the separate FFmpeg camera video. Future confirmation must validate current in-memory source state and use the actual analyzed snapshot.
