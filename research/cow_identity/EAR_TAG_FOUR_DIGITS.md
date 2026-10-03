# Four-digit text is not yet a verified work number

The user needs the four-digit farm work number, not necessarily the complete
national identifier. The current public corpus cannot measure that semantic task:
its labels contain text polygons and literal strings, with no field role,
completeness flag or link to an animal. Of the original 64 exposed tag images,
18 contain one literal ASCII four-digit line. No calibration or reserved examples
were inspected for this diagnostic.

The [Gao et al. dataset paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11014036/)
describes Chinese cattle-tag localization and text transcription data. These
annotations do not establish Dutch work-number layouts. In eight fixed exposed
examples, `1210` and `1217` look like small date-like fields beside longer main
numbers; `1601` and `1602` are visibly cut off or occluded. These are observations,
not corrected semantic truth. All 18 original targets remain in the experiment.
The source hashes, literal targets and visual caveats are recorded in
[four-digit-semantics.json](results/2026-10-03/ear-tags/four-digit-semantics.json).

## Cached transcription comparison

This is retrospective and exploratory. Both scripts use the same strip-only
ASCII-four-digit helper. Every emitted four-digit string counts, including strings
on other-length truth lines or unmatched geometry. Unique polygon IoU matching
still uses all 157 original line annotations; no date-like or partial example was
removed. No model, confidence gate, reference image or historical result changed.

| Cached condition | Literal correct / emitted | Correct / 18 targets |
| --- | ---: | ---: |
| Original RapidOCR, all readings | 7 / 12 | 38.9% |
| Original RapidOCR, confidence ≥ .95 | 7 / 11 | 38.9% |
| Corrected adapted TrOCR on original detected lines | 8 / 14 | 44.4% |
| Original detector, literal reader agreement | 7 / 9 | 38.9% |
| OBB detector, identical literal reader agreement | 7 / 7 | 38.9% |
| Corrected adapted TrOCR with provided true line polygons | 13 / 16 | 72.2% |

The new line detector removed two unmatched four-digit outputs, but did not add
correct four-digit targets. Its seven correct strings include `1601` and `1602`;
**7/7 literal transcription is not seven established work numbers**. The oracle
row also depends on supplied text locations and is not camera performance.

Original results are preserved in
[four-digit-exploratory.json](results/2026-10-03/ear-tags/four-digit-exploratory.json);
the additional OBB row is in
[four-digit-obb-exploratory.json](results/2026-10-03/ear-tags/four-digit-obb-exploratory.json).
The latter verifies the original detector/reader bindings and all 152 shared crop
files, then exactly replays the original all-line counters before computing the
new row. That is a shared-scorer provenance check, not an independent matching
implementation. Two CPU behavior checks cover leading zeroes, other-length truth,
duplicate geometry, wrong digits and missed targets.

## Next localization experiment: preserve source scale first

First test the existing checkpoint on fixed 1,280-pixel native image tiles with
20% overlap, every tile included and public class-aware NMS after translation to
source coordinates. This costs 55 model calls on the same 11 exposed images and
isolates input scale without retraining: six 4,000-pixel outdoor frames previously
lost almost 70% of their linear detail before inference. The three low-resolution
images remain unchanged single-tile controls. The fixed control has now run:
outdoor matches fell from 12/33 to 11/33 while unmatched predictions rose from
1 to 15. The three small images passed exact raw, input-shape and post-merge
parity; all 44 tag and 12 reviewed head annotations remained in the denominators.
This rejects source-scale preservation alone as a repair for the tiny 13-ROI
training set; it does not show native pixels are unnecessary for later OCR.
See the complete [tile score](results/2026-10-03/ear-tags/localization-tiles-score.json).

If more training data is still needed, use a tag-only detector on a reviewed, scene-grouped
subset of the author's [CEID-D whole-frame dataset](https://www.kaggle.com/datasets/fandaoerji/cow-eartag-detection-dataset),
with native-resolution tiles using the existing [SAHI library](https://github.com/obss/sahi).
This changes data diversity and retained pixels, rather than repeating the
13-ROI head/tag training with another parameter setting. SAHI supports Ultralytics
and slicing of annotated images; it is not a pretrained cattle-tag model.

Preparation should begin with at most 256 image/label pairs, grouped by scene and
near-duplicate capture before any training. The cached author index contains
2,675 JPEGs but only 2,451 text label files, despite the paper's equal-count
description. Missing annotation files must not become empty negative examples.
Completeness review is also required: our small earlier annotation study found
visible tags absent from the publisher labels. Keep all already exposed scenes
in development, and freeze any genuinely new scene test before model output.
Do not claim farm or animal independence without metadata supporting it.

Freeze one tile size/overlap and source-coordinate merge rule after that data
review. Count all whole-frame tags, including border fragments and misses.
Native tiles can prevent losing pixels when a large source image is reduced to
1,280 pixels; they cannot recover characters already tiny in a low-resolution
camera image. Reuse the existing body/pose/tracking work for owner candidates and
evaluate tag-to-animal attachment separately. No data or model was downloaded,
and no new training was performed for this recommendation.

For actual work-number validation, add explicit field-role and completeness
annotations on verified tag layouts: tag polygon, work-number polygon/string,
visible side, occlusion, other text roles, and the current animal owner with
capture/scene provenance. Preserve leading zeroes and include misleading dates
and truncated long identifiers as negatives. A four-digit filename alone is
insufficient: the public Dutch [CORF3D cattle data](https://github.com/ameybhole/CORF3D_HCR)
has useful animal/day metadata but is a side-view coat-recognition collection,
not a verified printed-work-number dataset. Its image archives were not downloaded.
