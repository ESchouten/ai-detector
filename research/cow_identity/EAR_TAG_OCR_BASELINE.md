# Ear-tag OCR: frozen development diagnostics

These experiments test literal text on public images, not automatic cow identity.
No result authorizes naming a tracked animal. A usable automatic system also needs
the correct identifier field, correct tag-to-animal ownership, independent later
evidence, and a reversible response to conflicting readings. A generic OCR score
is not a calibrated probability of the complete identifier being correct.

## Data and separation

The [Sensors 2024 source](https://pmc.ncbi.nlm.nih.gov/articles/PMC11014036/)
links the author's [recognition dataset](https://www.kaggle.com/datasets/fandaoerji/cow-eartag-recognition-dataset)
and [detection dataset](https://www.kaggle.com/datasets/fandaoerji/cow-eartag-detection-dataset).
The recognition archive actually contains 3,204 JPEG/annotation pairs, fewer than
the 3,238 described upstream. It includes short herd/date lines and longer numbers,
printed and handwritten text, cropped edges and poor visibility. It does not
certify biological identifiers or country-specific number formats. The public
metadata reports the license as unknown; this is a local noncommercial research
trial with recorded provenance, not a redistributed dataset.

[Dataset protocol](eartag_dataset_protocol.json) groups shared annotated numeric
strings, exact pixels and near-duplicate images before a deterministic split.
Leading-zero aliases are grouped to reduce leakage, never normalized in text
scoring. This cannot resolve undisclosed source-video groups, transcription errors
or all partial-number aliases. Development/calibration/reserved contain
1,650/656/597 images; another 301 have ambiguous identity grouping. The fixed pilot
is one image from each of 64 development groups, selected by source-file hash.
Its 157 annotated lines all remain in the denominator. Calibration and reserved
images have not been passed to OCR.

The archive is 28.4 MB, SHA-256
`4f0aa55d97cae2052933bf614f62200f89aeadb02563f7ccd49bff7e139cb65a`.
Local images and full manifests are ignored research assets; recorded protocols
bind them. The inventory script preserves original JPEG bytes and annotations.

## Frozen small-model baseline and oracle localization

RapidOCR 3.9.2, ONNX Runtime 1.30.0 and the official PP-OCRv6-small detector/reader
ran on CPU with two intra-op/OpenCV threads and one inter-op thread. Models were
local and hash-pinned. The engine received pixels only; the scorer loaded labels
after every raw output was saved. Exact text comparison strips outer whitespace
only. Zeros, punctuation and all lines matter. Unique polygon matching uses
IoU ≥0.5, maximizing match count before overlap. Missed lines, wrong text and extra
outputs are retained. Full-tag exactness requires all lines correct and no extras.

| Condition | Correct lines /157 | Wrong matched lines | Missing/rejected lines | Extra outputs | Full tags /64 |
|---|---:|---:|---:|---:|---:|
| Small, all raw | 74 | 20 | 63 | 24 | 12 |
| Small, score ≥0.95 | 65 | 6 | 86 | 11 | 9 |
| Same reader, oracle line boxes, all raw | 116 | 41 | 0 | not possible by construction | 31 |
| Same reader, oracle line boxes, score ≥0.95 | 104 | 9 | 44 | not possible by construction | 24 |

The small full pipeline's accepted exact precision is **65/82 =79.27%**, despite
the 0.95 confidence gate. Even supplied the publisher's line polygons, accepted
precision is **104/113 =92.04%**. These are different conditional tasks: the oracle
cannot produce detector extras. It is a diagnostic, not a better automatic result.

The full small pipeline took 12.42 seconds for 64 images, median 189 ms/image.
The oracle reader took 2.79 seconds for 157 lines, median 16.9 ms/line. Both used
actual CPU providers; no GPU or crop-specific tuning was used.

All six high-confidence full-pipeline errors were visually reviewed after scoring.
Three visibly truncate an annotated line: `7-21→7-2`, `8.31→31`, and
`40221→4022`. Others include digit confusion and ambiguous low-resolution edges.
No labels were changed or errors excluded. The oracle still emits high-confidence
truncation such as `20567→205` at 0.99977. The correct response is not to interpret
that score as naming certainty.

Evidence: [small raw/accepted score](results/2026-10-03/ear-tags/ocr-development-score.json),
[six-error visual audit](results/2026-10-03/ear-tags/ocr-high-confidence-error-review.json),
[oracle score](results/2026-10-03/ear-tags/oracle-line-score.json),
[oracle finiteness audit](results/2026-10-03/ear-tags/oracle-line-finiteness-audit.json).

## One stronger pretrained pair: rejected

The [official PP-OCRv6 report](https://arxiv.org/abs/2606.13108) motivates a larger
medium detector/reader, and the
[RapidOCR model catalog](https://github.com/RapidAI/RapidOCR/blob/v3.9.2/python/rapidocr/default_models.yaml)
provides pinned ONNX weights through the existing library. The two models total
138.75 MB. The comparison changed only those weights and their model-type metadata;
the 64 images, orientation classifier, CPU settings, pipeline and scoring remained
fixed. No model or threshold search followed the results.

| Medium condition | Correct lines /157 | Wrong matched | Missing lines | Extras | Full tags /64 |
|---|---:|---:|---:|---:|---:|
| All raw | 66 | 18 | 73 | 23 | 8 |
| Score ≥0.95 | 60 | 8 | 89 | 11 | 7 |

Accepted precision fell to **60/79 =75.95%**, and line coverage to **38.22%**.
The same64 images took **60.45 seconds** with no cache hits, compared with12.42
seconds for the small pair. The larger generic model is not promoted. Both
detector localization and recognition under ear-tag image conditions need attention;
raising the confidence threshold or citing a generic benchmark would not establish
automatic naming reliability.

The first launch stopped before model construction because the SDK expects a
`ModelType` enum while the frozen JSON held a string. The
[v2 protocol](eartag_medium_control_v2_protocol.json) binds a narrow enum-conversion
adapter, preserving the first protocol and failure log. No cattle outputs preceded
that correction. An independent review verified all166 bindings and unchanged
effective inputs/settings before inference. All107 raw output scores were finite
and within[0,1] before scoring.

Evidence: [medium score](results/2026-10-03/ear-tags/medium-development-score.json),
[raw output](results/2026-10-03/ear-tags/medium-development-raw.json), and
[finiteness check](results/2026-10-03/ear-tags/medium-finiteness-audit.json).

## Native images and ownership feasibility

A separate, label-blind sample selected 32 uniformly spaced numeric filenames from
the full detection inventory. Only these files and available annotations were
downloaded: **94.13 MB**, not the 7.9 GB archive. Three images have no published
annotation file and remain unannotated, not assumed empty. The 29 labeled images
contain 125 tag rectangles; the median minimum side is 69 pixels, and 104 have
both sides at least 40 pixels. Rectangle size alone does not guarantee readability.

The current source resize is a maximum **width** of 1280, with an even rounded
height and no upscaling. Applying that geometry to these annotations reduces the
number of tags with both sides at least40 pixels from104 to53. Portrait images
use the actual width rule, not a longest-edge cap. This
[pixel-support diagnostic](results/2026-10-03/ear-tags/ownership-resolution-diagnostic.json)
is not an OCR accuracy estimate. Any future native-resolution OCR path must retain
the original source pixels; a callback receiving an already resized analyzed frame
does not recover lost characters.

Some frontal feeding-barrier images expose a tag clearly attached to a particular
head. Rails, overlapping animals and cropped bodies make whole-animal association
less certain. The 640×368 image group has roughly 10–23-pixel tags, with no useful
visible characters. Several high-resolution examples show readable handwritten
lines, but also blur, edge-on tags, dates and herd labels. These are visual
observations, not ownership ground truth or automatic recognition measurements.

The files contain no cow-body instances, tag transcripts, biological IDs or video
timestamps. Their filename order is not a temporal tracking label. These two
author datasets also share collection context, so they cannot be called independent
cross-farm validation without checking source overlap.

See the [exact subset freeze](eartag_ownership_subset_v2_protocol.json),
[inventory](results/2026-10-03/ear-tags/ownership-subset-inventory.json), and
[source-only feasibility review](results/2026-10-03/ear-tags/ownership-subset-review.json).
The initial unexecuted subset draft used rounding instead of the approved explicit
floor-spaced list; v2 corrects that before any image inspection. Large individual
Kaggle files arrive as single-member ZIPs; extraction checked expected name and
size and never changed the selected images.

## Reproduction

Use the isolated OCR environment with versions bound in each protocol; the app
environment intentionally does not gain OCR/SciPy dependencies. `eartag_ocr.py`
provides `freeze`, `infer`, and `score` commands. `eartag_line_control.py` provides
the same commands for the oracle diagnostic. Run inference to a new path, then
score its completed immutable output. The protocol validators check libraries,
sources and weights. Source JPEGs are decoded to verify the original inventory
pixel hash; the actual BGR inference hash is recorded too. OpenCV4 inventory and
OpenCV5 OCR produced identical grayscale pixels for all64 pilot images.

Seven focused scorer tests cover literal zeros/punctuation, multiline completeness,
one-to-one matching, missing/rejected/invalid lines and absence of label text from
oracle inference inputs. No tests download models. Local cache/data files needed
for a replay must be downloaded/prepared from the recorded public sources; they
are not part of the repository.

Medium inference uses `eartag_medium_run.py infer` with the v2 protocol; scoring
uses the unchanged `eartag_ocr.py score`. CPU sessions reported only the CPU
execution provider. ONNX Runtime emitted an import-time telemetry-storage warning
and created a small `:memory:.ses` session file despite the subsequent explicit
telemetry-disable call. The file was moved to the ignored research cache after
all OCR runs, not committed. No network-blocking guarantee was tested; model files
were local and pinned, and the runner contains no image-upload operation.
