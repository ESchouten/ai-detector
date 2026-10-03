# Independent annotation audit, 3 October 2026

**The low localization coverage is not explained by a broken pickle conversion, reversed coordinates, incorrect video, or an off-by-one frame lookup.** Independently recovered publisher arrays match the existing numeric NPZ. Nine inspected development frames show correct spatial alignment. The general-purpose detector visibly misses calves and combines adjacent animals into single boxes.

## Original data, without executing pickle instructions

The original `pmfeed_4_3_16.pkl` has SHA-256 `2c5dbf9c7856bfb15fe38b99487ff576f1b281fcf70af84cc0ac982af1ef203e`. [annotation_audit.py](annotation_audit.py) accepts only that artifact. It parses its protocol-5 opcodes with `pickletools.genops`; it never imports pandas, calls `pickle.load`, or executes `GLOBAL`, `REDUCE`, `NEWOBJ` or `BUILD` instructions.

Manual opcode inspection established the following layout:

| Buffer | Numeric interpretation | DataFrame columns |
| --- | --- | --- |
| 0 | 537,910 little-endian int64 values | `class` |
| 1 | 5 × 537,910 little-endian float64 values, C order | `x`, `y`, `w`, `h`, `conf` |
| 2 | 537,910 little-endian int64 values | `tracklet_id` |
| 3 | 537,910 little-endian int64 values | `frame_id` |
| 4 | 537,910 little-endian int64 values | DataFrame row index |

The reader extracts these raw `BYTEARRAY8` payloads with NumPy. It validates the observed buffer sizes and column names; it is an artifact-specific audit utility, not a general pickle reader.

After sorting original rows by `(frame_id, tracklet_id)` and casting to the existing conversion's dtypes, **every value in all six required columns matches exactly**: frame ID, calf ID, x center, y center, width and height. The previous conversion sorts rows and stores coordinates as float32. Original coordinates are float64; this is ordinary precision reduction, not a different coordinate convention.

The original contains 537,910 rows. The paper/card's prose says 537,908. We retain the actual artifact's rows rather than silently remove two to match prose.

## Coordinate and time contract

The [publisher's cropping script at the pinned dataset revision](https://huggingface.co/datasets/tonyFang04/8-calves/blob/7394fdefc4aeafd530856b397623b8f833a86488/identification_benchmark/crop_pmfeed_4_3_16.py) independently confirms normalized center-x, center-y, width, height. It seeks the video at `frame_id - 1` and uses the same center-to-corner transformation as our evaluator. That script was read, not executed; its SHA-256 is `4d90957c5b558c3f23362756fca3ab3b8cd26699bbc09c9b8498ff6cfa8a3f08`.

The local source video SHA-256 is `475824794af23d28d9d92039eb893d73ab0374c8b3272d42c176b5f363cd9825`. OpenCV reports **800 × 600, 20 fps, 67,760 frames**. Original labels span **1–67,760**. Therefore second 330 corresponds to zero-based video index 6,600 and publisher frame ID 6,601. The current assessment uses this convention correctly.

## Visual check against actual inference

We rendered original publisher boxes alongside actual local YOLO26m-seg predictions at **0, 1, 10, 330, 331, 340, 930, 931 and 940 seconds**. This audit used CPU FP32, 640-pixel inference, cow class and confidence ≥0.25. It is a localization sanity check, not a replay of the earlier MPS FP16 tracked evaluation.

All nine original-label panels align with the visible individual calves. At the first frames, the left foreground calves have overlapping individual labels; YOLO often misses them or groups them together. At 330–340 seconds, the same merging problem occurs in the feeding row. At 930–940 seconds, dense adjacent animals are represented by very few broad detector boxes: the frame at 930 seconds has eight publisher boxes and one detector box. The issue is visible before identity matching or temporal agreement runs.

The publisher boxes describe individual animal extents; they are not body-part crops or segmentation masks. Under occlusion their rectangular crops contain neighboring animals. Correct geometry therefore does not imply clean recognition evidence.

Generated side-by-side JPEGs are local under `.cache/cow-identity/annotation-audit/`. The compact [numeric audit report](results/2026-10-03/annotation-audit.json) records original and predicted boxes, source/model hashes, video properties and frame indices. Its `best_iou_per_truth` is a **one-to-many visual diagnostic**, not a coverage metric: one broad prediction can overlap multiple truths. The production assessment's one-to-one matching remains unchanged.

## What this does and does not establish

- The source-to-NPZ conversion and current spatial/frame conventions are verified independently.
- The observed general-purpose detector failures are real. Dedicated localization training or a better suited detector is justified; changing evaluation coordinates is not.
- This inspection does not re-annotate all identities or certify the full dataset. The [paper](https://arxiv.org/html/2503.13777v2) describes detector-assisted annotations with manual corrections and approximately 3,000 missing boxes. Its 0.56% figure concerns missing boxes, not a guarantee of 99.44% identity-label accuracy.
- Reserved video windows **1800–2099 and 2700–2999 seconds were not decoded, viewed, inferred or scored**. Full-array equality was checked for conversion provenance only.
- No production inference, configuration or evaluator metric was changed by this audit.

## Reproduce

Use the existing application environment and downloaded official files; the script does not download weights or data:

```sh
ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS=1 detector/.venv/bin/python \
  research/cow_identity/annotation_audit.py
```

Paths and device can be overridden with `--publisher`, `--converted`, `--video`, `--detector`, `--output`, and `--device`. The development timestamps are fixed in the script. Source attribution: [tonyFang04 / 8-calves](https://huggingface.co/datasets/tonyFang04/8-calves), CC BY 4.0; generated panels annotate its public video with publisher labels and independent model predictions. Dataset video and images are not included in the repository.

## Follow-up: biological identity versus tracklet number

The numeric conversion audit alone does **not** establish that a label always
follows the same physical calf. A later segmentation montage raised a specific
concern: calf 8's rear view at 0 seconds resembled calf 5's rear view at 330
seconds. We checked this separately before further identification training.

The [pinned publisher README](https://huggingface.co/datasets/tonyFang04/8-calves/blob/7394fdefc4aeafd530856b397623b8f833a86488/README.md)
explicitly defines `tracklet_id` as calf identity 1–8 and uses it for chronological
identity classification. These are intended as persistent animal labels, rather
than arbitrary short-lived tracker IDs. That intention is not independent proof
of their correctness.

[identity_continuity_audit.py](identity_continuity_audit.py) reads the original
publisher arrays without unpickling. It produces context frames and crops with
preserved proportions at 0, 330, 930 and 1230 seconds for all eight calves. It
also follows calves 5, 8 and 6 every 15 seconds from 0–360, then every 60 seconds
from 330–1230. No identity predictions or segmentation masks enter this check.

The intervening images do **not** support the suspected 5/8 switch:

- Calf 5 remains lying in the rear-right area through 270 seconds, with a white
  rump and dark middle. At the same times calf 8 is separately visible walking
  around the pen. Around 285–330 seconds calf 5 stands and moves toward the rear
  feeding corner, explaining its new rear view.
- Calf 8 retains a predominantly black back with small, isolated white dorsal
  marks as it reaches the foreground. Its body markings differ from calf 5's
  broad white rump. Calf 6 provides another independent comparison, with two
  larger dorsal patches that remain recognizable through the sampled sequence.
- At 930 and 1230 seconds these distinctive marks remain compatible with their
  earlier labels. The calf-8 rectangle at 1230 includes much of a neighboring
  white-backed animal; a broad rectangular crop is not a clean identity portrait.
  That is a concrete source of recognition ambiguity without a label switch.

This is a **bounded visual check**, not a full-frame identity certification. It
resolves the specific apparent swap well enough to retain the original labels;
it neither changes labels nor removes difficult examples from metrics. Sparse
inspection can miss short identity errors. The reserved 1800–2099 and 2700–2999
windows remain unopened.

Reproduce without GPU, downloads or recognition inference:

```sh
detector/.venv/bin/python research/cow_identity/identity_continuity_audit.py
```

The ignored `.cache/cow-identity/continuity-audit/` directory contains the source
context, chronological contact sheets and a manifest of every selected frame,
box and publisher identity, with original source hashes.

## Blinded extent audit after the continuous-tracking experiments

**Completed on 2026-10-03 after the sampling protocol was frozen.**
The later continuous-tracking experiments have now exposed the five scored
panels, including 1800–2099 and 2700–2999. The earlier statements that those
panels were unopened describe the original audit above. Footage at 3000 seconds
and later remains closed. This pass reviewed geometry only; independent
biological identification was deliberately deferred rather than forced from
ambiguous coat fragments.

### What the publisher actually establishes

The [paper, sections 2–3](https://arxiv.org/html/2503.13777v2#S2), describes 900
manually boxed frames used to train YOLOv8m, followed by ByteTrack and manual
correction of false positives, swapped identities and missed tracks in one video.
The authors acknowledge approximately 3,000 missing boxes and detector-family
bias from that annotation procedure. It does not specify a reproducible rule
for visible-only versus inferred occluded body extents, or supply independently
verified instance masks. These limitations justify auditing geometry separately;
they do not establish that our unmatched named predictions are biologically
correct. The original numeric conversion and pixel/frame alignment remain
verified by the artifact-specific checks above.

The current [frozen metric](ITERATION_PROTOCOL.md) maximizes one-to-one match
cardinality at IoU ≥0.5 before maximizing IoU. It does not use the proposed name
to choose an association. Every named unmatched output remains an error. This
can penalize a tight visible mask against a larger publisher rectangle, but can
also correctly reject a partial animal, merged body or duplicate. A visual
impression that one example contains the right calf does not separate those
causes over the whole recording.

### Fixed, small sample

Use four equally spaced midpoint samples within each already-exposed panel:

| Exposed panel | Frozen seconds |
|---|---|
| 330–629 | 367, 442, 517, 592 |
| 930–1229 | 967, 1042, 1117, 1192 |
| 1230–1529 | 1267, 1342, 1417, 1492 |
| 1800–2099 | 1837, 1912, 1987, 2062 |
| 2700–2999 | 2737, 2812, 2887, 2962 |

The rule is `panel_start + 37 + 75*k` for `k=0..3`, independent of model outputs,
confidence, error locations or publisher box quality. Review every visible calf
in all 20 frames, including unknown calves and partly hidden animals. Do not
replace difficult frames, fill the sample with known failures, or infer eight
visible bodies just because eight calves exist in the recording. Save source
hashes, zero-based video frame `20*second`, original pixel hashes and the sample
rule before review. No model inference is needed.

### Two-stage review with preserved uncertainty

1. Two reviewers independently inspect native source images without prediction
   overlays, publisher rectangles, confidence values or outcome labels. Draw a
   tight rectangle around the **visible** animal pixels, including visible head,
   feet and tail; do not infer hidden body area. Label local objects A, B, etc.,
   and explicitly record truncation, occlusion, fragmented visibility and
   inseparable neighboring bodies. Keep uncertain objects rather than dropping
   them. Fixed source context at `t-1`, `t`, `t+1` is available for every sampled
   frame; it is only annotation assistance, never model input for this audit.
2. Freeze both complete reviews and compare anonymous instance geometry before
   showing publisher labels or any model output. Adjudicate disagreements using
   only the same clean centers and fixed context, preserving both originals.
   This pass makes no biological identity claim. The reviewers are AI agents,
   so the result is **independent AI-assisted review**, not external human truth.
3. Reveal publisher boxes and identities, then all cached predictions for the
   same sampled frames, including unnamed predictions and apparent successes.
   Classify each discrepancy: missing label, suspected biological-ID mismatch,
   extent-convention mismatch, partial prediction, merged bodies, duplicate,
   or unresolved. A box containing much background is not automatically a bad
   annotation: the author may have intended an occluded/amodal extent.

Report reviewer agreement, visibility/ambiguity counts, publisher-versus-visible
box extent differences, and discrepancy categories on this complete sample.
An optional mask-contamination judgement should ask whether foreground includes
another animal, independently of the rectangular extent. Preserve initial
reviews alongside any adjudication so certainty is not manufactured afterward.

This is a diagnostic audit, **not replacement truth or an alternate passing
score**. Do not change frozen labels, remove disputed observations, lower IoU,
or recalculate acceptance against the new rectangles. Twenty correlated frames
cannot certify 99% naming precision; report counts, not an animal-level or
cross-farm confidence claim. Existing failed runs remain failed.

If the sample shows substantial extent disagreement, the next validation needs
a new short recording with an agreed visible/occluded-box convention and actual
independent animal identities, annotated before viewing model predictions. It
should include entrants, crowded crossings, exits and reconnection, and report
both localization and biological naming. A cleaner new test is stronger evidence
than repeatedly redefining success on this already-studied public video.

### Results and limits

The [frozen sample](annotation_geometry_protocol.json) produced 20 native centers
plus fixed ±1-second context. Both complete reviews were frozen before sharing
labels: [audit reviewer](results/2026-10-03/geometry-review-audit.json) and
[cattle reviewer](results/2026-10-03/geometry-review-cattle.json). Both had prior
general scene exposure, although the sample was selected independently of
prediction outcomes. The comparison found 159 versus 160 possible instances,
156 nonzero-overlap anonymous pairs and median paired IoU 0.858. Uncertainty
flags differed substantially: 38 versus 113. High rectangle overlap therefore
does not establish equal interpretation of occlusion or correct instance counts.

The [raw-only adjudication](results/2026-10-03/geometry-review-adjudication.json)
records actual reviewer mistakes: the audit review invented a top-border object
at 517/592 seconds, merged foreground bodies, missed a separate crowded body at
1267, and split one bent animal at 1492. It also omitted a visible head outside
the rail at 442. The original files remain unchanged. Tiny upper-edge possible
fragments at 2887/2962 remain uncertain rather than becoming definite extra cows.

Only afterward, [all cached outputs and original publisher boxes were
revealed](results/2026-10-03/geometry-review-reveal.json) for these same centers.
No new model inference or alternative accuracy calculation was performed.
There are 158 publisher boxes. Descriptive anonymous publisher/reviewer matching
gives median IoU 0.754/0.775 and median publisher-to-review area ratio 0.898/0.912.
These are geometry-agreement summaries, **not model accuracy or replacement
truth**; they include uncertain regions and preserved reviewer mistakes.

The sample does **not** support a general claim that publisher boxes are too
loose. They are typically slightly smaller than the visible-all-parts estimates.
Some crowded rectangles are larger or smaller, reflecting head/foot inclusion
and unclear occluded-body ownership. The upper-left calf at 1117 is one concrete
large-extent outlier; the lower-right calf at 1417 has a smaller publisher extent
than the visible-all-parts reviews. Both situations remain anatomically uncertain.
The model has real geometry failures too: at 1267/1342 a mask absorbs neighboring
body pixels while another slot collapses to a fragment; those names are withheld.
Raw YOLO outputs also contain partial/duplicate or merged-body proposals.

The [complete frame notes](results/2026-10-03/geometry-review-interpretation-audit.json)
and [second review of the later 12 centers](results/2026-10-03/geometry-review-interpretation-cattle.json)
agree on these limits and preserve favorable and difficult cases. This uniform diagnostic is distinct
from the earlier error-selected 35-case review. Neither establishes biological
name accuracy. Keep the existing conservative naming-plus-localization gate and
all failed results unchanged. For a farmer-readiness claim, the next independent
recording needs verified animal identities and a pre-agreed visible-instance
annotation convention, with human/domain review before model predictions are
shown. Relabeling this studied video until an algorithm passes is not validation.

Reproduce the reveal locally with
`detector/.venv/bin/python research/cow_identity/annotation_geometry_reveal.py`.
It refuses to overwrite its image output directory; the already rendered native
panels are under `.cache/cow-geometry-audit/revealed/`.
