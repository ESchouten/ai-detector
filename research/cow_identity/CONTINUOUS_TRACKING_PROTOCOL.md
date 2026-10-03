# Continuous tracking evaluation: proposed addendum

**Status: draft; reserved footage has not been opened.** Finalize this addendum
only after the combined application-runtime development run, independent replay
and focused tests pass. Preparation or execution of reserved footage also needs
the parent's explicit authorization. The associated
[protocol template](detection_reserved_protocol.template.json) is intentionally
not executable as a finalized evaluation.

The original [iteration protocol](ITERATION_PROTOCOL.md) remains unchanged. Its
disconnected-window identity/tracker resets describe fresh-window recognition.
The proposed experiment tests a different capability: preserving names during
one uninterrupted recording after farmer-like confirmation of initial animals.
It cannot establish recognition after a restart, a new arrival or re-entry.

## Method selected before reserved input

- Use the same reviewed actual first-frame proposals and SAM masks, with
  original slots 1–6 named and slots 7/8 anonymous. Source frame zero appeared
  in detector training, so initialization is optimistic.
- Process seconds 0–2999 continuously at two frames per second: exactly 5999
  source frames, native zero-based indices `0, 10, ..., 59980` at 20 fps.
  No later truth-derived prompt, identity correction, enrollment or state reset.
- Run the application PyTorch environment with Cutie FP32 and raw YOLO FP16
  in the same MPS process. Use the selected 480-pixel Cutie configuration and
  unchanged mixed detector at confidence 0.40/image size 640.
- Once per integer second, use original mask probabilities, largest-component
  rectangles, probability ≥0.70, the fixed corroborated-recovery quarantine and
  reciprocal same-frame detector pairing at IoU ≥0.50. Names and masks are
  never reassigned. The complete policy is recorded in the
  [selected development freeze](detection_recovery_consensus_protocol.json).
- Intermediate half-second frames update video memory only. They do not reuse
  old detector evidence as a new confirmation.

The intervening frames, including the gaps between scored panels, are causal
tracking input. They cannot supply labels, tune a threshold or refresh a name
from ground truth. This is continuous within-camera tracking, **not** an
independent farm, disconnected-window recognition or a pristine dataset.

## Freeze and source preparation

First bind the successful combined development run, exact implementation,
weights, libraries, source-video hash and this complete method in a finalized
selection plan. Do this before decoding any additional source pixels. After
explicit authorization, prepare the lossless source clip and its exact pixel
manifest. A derived execution/evaluation manifest may add their checksums; it
must retain the selection plan's method and endpoints unchanged. No selection
decision may use the new pixels, predictions or reserved annotations.

Only after complete inference is saved may the scorer access reserved truth.
An interrupted or resource-aborted run is an incomplete experiment, not a
shorter denominator or a successful fast run. Preserve every failure. If the
method later changes, these panels become exposed and cannot be called an
untouched holdout again.

## Counts and acceptance

Score **1800–2099** and **2700–2999**, inclusive, at one-second timestamps:
300 frames per panel, 600 scored frames total. Do not score the 600-second gap
when pooling. Each panel and the pooled counts must meet the originally stated
targets: at least 99% conservative named precision, at least 60% correct naming
coverage of all visible enrolled animals, and at most 1% false naming of visible
anonymous animals. Retain missed detections, rejected names and named unmatched
boxes. Use the existing maximum-cardinality-then-IoU one-to-one matcher at 0.5.

The scorer evaluates the names actually emitted online, not a retrospectively
recomputed policy. Report correct names, wrong known names, unknown animals
named, named unmatched boxes, visible known/unknown denominators, localization
and identity switches. Pooled rates are computed from summed raw counts, never
the average of window percentages. Report global anonymous ID-F1 separately
from correctness of the original assigned names.

Frames within this video are strongly correlated. Report raw counts and the
observed range between the two panels; do not present a per-frame binomial
confidence interval as uncertainty about performance on other farms. Two
windows from one recording do not provide independent deployment evidence.

## Actual runtime cost

Retain every input-frame duration, initialization time, decode/hash time,
synchronized Cutie/YOLO time, policy/cache time and Metal cleanup cost. Report
elapsed time, mean/p95/p99 and fraction above the 500 ms input interval, plus
peak observed driver allocation/RSS and bounded SDK/quarantine state. Verify
actual MPS devices and FP32/FP16 precision; CPU fallback is a different run.
Resource caps protect the machine but do not by themselves demonstrate real-time
throughput. This one-camera result does not establish how many cameras run
concurrently with the web app, recordings and notifications.
