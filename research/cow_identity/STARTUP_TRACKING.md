# Anonymous startup propagation

This is a bounded deployment-gap experiment, separate from the earlier manually selected seeds and from appearance recognition. It uses the exposed first120seconds of the eight-calves recording. The detector trained on early frames from this recording; this is optimistic feasibility evidence, not independent farm validation.

## Frozen procedure

The [v3 protocol](detection_startup_control_v3_protocol.json) binds the runner, scorer, installed SDK, weights, source clip, selection policy and safe annotation provenance before inference. Six behavioral tests and an independent read-only preflight passed. Two earlier preflights failed before any model call because of namespace-package and JSON-key representation checks. Their [source snapshots and record](results/2026-10-03/detection/startup-control-preflights.json) are retained; all three versions have identical selected mask pixels and anonymous proposal maps.

All12 first-frame detector proposals and their original SAM masks enter the unchanged measured [containment policy](STARTUP_PROPOSALS.md). Every survivor enters Cutie; none is chosen or removed using an animal name or publisher label. Deterministic letters A–H follow ascending original proposal index. The indexed masks are disjoint by the established policy, and all selected objects remain anonymous.

This is explicitly a **single exact-frame** initializer. It does not use the earlier two-frame temporal admission gate, which retained only six objects. That earlier result remains unchanged. Later births and retirement are excluded from this short control to isolate whether automatically obtained initial masks propagate coherently.

The existing streaming pipeline processes241inputs at2Hz, from0through120seconds. Cutie uses FP32 and the raw detector FP16 on the same MPS process; the detector and unchanged geometry-quality/quarantine policy run at1Hz. The installed combined SDK has separate CPU and MPS proofs showing exact previous-joint probability parity on16synthetic steps with insertions and consolidation. Those are compatibility prerequisites, not evidence that new cattle masks will reproduce the old manually seeded trajectory.

No truth is loaded by the inference wrapper. Only after complete source-bound output is saved may the scorer associate the **supplied initial mask boxes** with first-frame publisher boxes, using the existing maximum-cardinality then maximum-IoU one-to-one matcher atIoU≥.5. This fixes each anonymous slot's initial geometric anchor. Unmatched or duplicate initial slots never gain an anchor later.

Every integer second1–120 is scored. All visible annotated animals and all predicted boxes remain in the denominator. Correct initial-instance associations, wrong-animal associations, unmatched anchored boxes, unanchored boxes, misses and switches are retained. Global optimally remapped ID-F1 is reported separately: it cannot excuse an initial slot changing animals. The original seed frame establishes anchors and is excluded from subsequent quality counts.

The resource stop is8GiB post-reclamation driver allocation or process peak RSS; a sustained one-second processing time is a safety stop. Real2Hz throughput requires mean input time≤.5seconds and is reported separately, together with tail latency and memory maxima. This short run cannot demonstrate indefinite uptime.

## Observed result

The [immutable assessment](results/2026-10-03/detection/startup-propagation.json) completed all241inputs and121cached integer-frame masks without a resource stop. All eight automatically selected masks received distinct first-frame geometric anchors only after inference. No biological names were supplied to the model.

| Fixed initial-instance outcome, seconds1–120 | Count |
| --- | ---: |
| Visible publisher annotations | 959 |
| Predicted anonymous instances | 960 |
| Correct original-animal associations | 952 |
| Wrong-animal associations | 0 |
| Unmatched anchored predictions | 8 |
| Missed annotations | 7 |
| Track-to-animal / animal-to-track switches | 0 / 0 |

The fixed-anchor coverage is952/959(**99.27%**); anchored precision counts all eight unmatched predictions as errors,952/960(**99.17%**). Global ID-F1 is99.22%, reported separately. Every slot produced a box on every scored timestamp; geometry errors are still counted rather than calling that perfect survival. The eight unmatched cases occur at4,6,31,85,97,98,99and117seconds. All named-output arrays remained empty.

The real same-process MPS run took36.04seconds including initialization. Mean input time was145.97ms, p95206.94ms and p99235.12ms. After the first initialization input, no frame exceeded the500ms input interval. Peak observed driver allocation was4.28GiB and process peak RSS1.22GiB; maximum observed working/long-term memory tokens were10800/1024. These are measured short-run maxima, not the configured long-term limits.

This supports the feasibility of automatically assembling useful **anonymous** initial objects in this particular scene. It does not overturn the later crowded-run precision failure, establish startup on another camera, or test a farmer's ability to confirm the correct animal.

## Human confirmation remains a distinct check

An anonymous track letter is not a biological identity. This experiment sends no farmer command and does not simulate a correct human answer from the scoring labels. The new pure live-confirmation state and separate transport adapter must later be exercised with a frozen analyzed snapshot, opaque instance/generation/revision, current source epoch and bounded command deadline. A confirmed name can attach to that still-continuous instance without inserting an old image or mask into the current model.

If the instance was retired or its continuity was lost, the old target must be rejected. A useful saved gallery photo must not thereby name a different animal occupying the same location. Temporary quality hiding and destructive continuity loss require explicit integration semantics; the research quarantine policy cannot silently be replaced by clearing every live assignment.
