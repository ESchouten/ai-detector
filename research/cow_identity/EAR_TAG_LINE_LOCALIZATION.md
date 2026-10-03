# Domain-adapted text-line localization

The original small RapidOCR detector matched only 94 of 157 annotated text lines
on the fixed 64-tag development panel. Changing its reader cannot recover the
other 63 lines. This separate experiment tests a small, domain-trained text-line
detector without changing the readers or choosing thresholds from its outputs.
It does not detect tags on whole animals or establish tag ownership.

## Fixed data and model

The training images are exactly the same 1,347 images in 478 development groups
used for the reader adaptation. Every image in any of the 64 pilot groups is
excluded. All 3,243 original line polygons are included as one detection class;
the detector receives no transcript. The calibration and reserved images remain
closed. See [data preparation protocol](eartag_obb_data_protocol.json).

The detector is the official Ultralytics
[YOLO11n-OBB checkpoint](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-obb.pt),
5,795,654 bytes, SHA-256
`b62898ebf38940ca4df323863e45ee9d84a1a46d5d11ebdde529fb33aa9f3a32`.
It is loaded through the existing native Ultralytics OBB trainer rather than a
new text-detection training stack.

Original image bytes are preserved. The four original polygon corners are
normalized to the image dimensions and written with ten decimal places. Maximum
coordinate round-trip error is 0.0000000204 pixels. The native dataset parser and
320-pixel training transform retain all 3,243 labels; none falls below the native
criterion's two-pixel side cutoff. The smallest transformed side is 18.67 pixels.

Native OBB training internally represents each quadrilateral as its minimum-area
rectangle. The median original-polygon/rectangle area ratio is 0.967, and the
minimum is 0.596. This representation difference is explicit: evaluation still
uses the original publisher polygons, not replacement rectangles.

## Fixed native training

The [training protocol](eartag_obb_training_protocol.json) binds the original
weights, one-class initialization, source images, labels, native library source,
runner and tests. Settings are 320 pixels, FP32 MPS, batch size 16, `nbs=16`,
20 epochs, AdamW at 0.001, weight decay 0.0005, seed 17, constant learning rate,
no warmup, no early stopping and no augmentation. The native optimizer, loss,
gradient clipping and EMA remain in use. Observation callbacks check finite
losses/gradients and exact optimizer/EMA counts; they do not replace training.

Both native training and validation paths contain only the same training images.
The SDK still performs its final validation and best-checkpoint revalidation;
those training-only measurements are not held-out evidence and do not select the
study checkpoint. Only native `last.pt`, exactly equal to the final EMA converted
to FP16, is eligible. Subsequent FP32 inference does not undo this native FP16
checkpoint serialization.

The separate 20-step timing preflight took 19.54 seconds and projected a full run
of 381 seconds. A fresh process then reloaded the original initialization and
completed all **20 epochs and 1,700 optimizer/EMA updates in 397.14 seconds**.
Every first-20 four-component loss matched the preflight exactly. All losses and
gradients were finite. Peak Metal driver allocation was 1.255 GiB and peak process
RSS was 3.000 GiB, within the fixed 900-second and 8-GiB caps. No restart or
checkpoint reselection occurred.

The final checkpoint SHA-256 is
`8585135e02d98c873e1c3c936ef29099b9ac3382ab579864cdda8650777dea7c`.
See [training report](results/2026-10-03/ear-tags/obb-training.json) and
[fresh-reset completion audit](results/2026-10-03/ear-tags/obb-completion-audit.json).

## Frozen evaluation

The [evaluation protocol](eartag_obb_evaluation_protocol.json) was frozen before
any pilot OBB predictions. It uses all 64 original images, FP32 MPS at 320 pixels,
confidence 0.25, NMS IoU 0.7 and at most 300 detections. Every native predicted
quadrilateral is retained. Its same four corners are reordered with RapidOCR's
existing helper, then the original SDK warp and orientation classifier prepare
one exact PNG for both readers. Invalid or subpixel crops remain explicit failed
readings instead of disappearing from detection counts.

The readers are unchanged small RapidOCR and the final corrected CPU-trained
TrOCR checkpoint. The frozen score reports raw readers, RapidOCR at 0.95 and the
existing literal-agreement rule. It preserves leading zeros and punctuation,
uses unique polygon-IoU matching at 0.5, and keeps all 157 annotated lines, all
misses and all extra predictions. No model, crop or threshold is selected from
these results. These are development measurements, not a new reserved test or
evidence that ear numbers can yet safely name animals.

Source review caught one invalid-crop bookkeeping error before any model call:
the prepared row carried its rejection reason while its empty reader row did
not. The first freeze and exact source/tests were preserved, the reason was
propagated consistently, and a regression was added. The corrected freeze is
`f4fc942165844abbf6339c8d778186760d4fcdc5c2ab4e670242f019150b4487`.
An independent reviewer verified all 7,995 bindings and four focused tests before
execution. No input, model or evaluation setting changed. The completed run had
no invalid crops.

## Result: better localization, remaining reading errors

The trained detector matched **148/157 lines (94.27%)**, missed 9, and produced
4 extra regions. The original small OCR detector matched 94, missed 63 and
produced 24 extras. This is a substantial improvement on the exposed development
panel. It is not yet a held-out result.

| Fixed reader condition | Correct / 157 | Wrong matched text | Missed lines | Extra predictions | Exact whole tags / 64 |
|---|---:|---:|---:|---:|---:|
| Small RapidOCR, raw | 110 | 38 | 9 | 4 | 23 |
| Corrected TrOCR, raw | 111 | 37 | 9 | 4 | 26 |
| Small RapidOCR, score at least 0.95 | 98 | 11 | 48 | 1 | 17 |
| Same-crop literal agreement | 85 | 2 | 70 | 1 | 12 |

Agreement retained 88 predictions, giving **96.59% precision and 54.14% exact-line
coverage**. That is still insufficient evidence for automatically assigning an
animal's number. Both readers can agree on a shared crop error. The fixed all-line
endpoint also includes dates and other printed fields; a later work-number
endpoint must be separately defined and cannot replace this result.

All three agreement errors are retained in the
[error audit](results/2026-10-03/ear-tags/obb-agreement-error-audit.json).
On `eartags1727`, the predicted region cuts off the final digit of `7-21`, and
both readers return `7-2`. On `eartags3155`, overlapping proposals read `20`
twice; one loses the publisher's leading punctuation in `.20`, while the other
is an unmatched duplicate. The underlying image makes that punctuation
ambiguous, but the original annotation and both errors remain unchanged. No
overlap threshold, padding or text normalization was adjusted after viewing them.

The detector, CPU small reader/crop preparation and MPS TrOCR stages took 3.78,
3.50 and 5.64 seconds respectively, including their initialization and validation
overhead. Peak Metal allocation was 0.067 GiB for detection and 1.150 GiB for
TrOCR. All stages stayed within their separate 180-second and 8-GiB execution
guards. Their exact executed watchdog source is preserved; a later readability
refactor did not repeat inference or change the frozen evaluator.

See [complete score](results/2026-10-03/ear-tags/obb-development-score.json),
[independent preflight](results/2026-10-03/ear-tags/obb-evaluation-independent-preflight.json),
and [execution provenance](results/2026-10-03/ear-tags/obb-execution-provenance.json).
All raw outputs remain alongside them. The promising direction is domain-specific
localization; reliable identity-field selection, animal ownership and independent
repeated observations remain separate requirements.
