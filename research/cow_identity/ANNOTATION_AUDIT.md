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
