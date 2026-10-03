# Cow identity: evidence and development direction

Research checked on 3 October 2026. This branch develops a local, farmer-operated
identity assistant. It does not yet establish reliable identification on a new
farm, at night, or for every breed.

## Decision

Start with **confirmed examples and conservative matching**, comparing frozen
animal encoders against a general DINOv2-small baseline. A farmer names a cow and confirms several clear sightings.
New sightings are compared with that gallery; uncertain sightings remain unknown.
Adding or correcting an example should not require training a neural network.

The [fresh exploratory comparison](BENCHMARK.md) selects **MIEWid for the trial**.
On the shared multi-view protocol, it correctly identified 88 of 89 accepted
queries at 69.84% known-cow coverage. MegaDescriptor correctly accepted 11 known
queries; DINOv2-small at 224 pixels accepted 17 queries, only 10 correctly. These are dataset
results, not a farm accuracy guarantee. The production-style three-sample
agreement check was much more conservative: 12 accepted known-cow groups, all
correct, but only 9.5% coverage. Actual camera-video testing is still required.

Keep the application model-independent: image encoding, matching, storage and
farmer review have separate responsibilities. Identity remains optional and must
not delay or interrupt the existing behaviour detectors.

The general-purpose baseline is the official
[facebook/dinov2-small](https://huggingface.co/facebook/dinov2-small), loaded with
the standard Transformers implementation. Meta's
[model card](https://github.com/facebookresearch/dinov2/blob/main/MODEL_CARD.md)
licenses these models under Apache-2.0 and describes nearest-neighbour retrieval
as a supported use. This establishes usable provenance, **not cattle accuracy**.

Pinned weights:

- Revision: `ed25f3a31f01632728cabb09d1542f84ab7b0056`.
- File: `model.safetensors`, 88,249,960 bytes.
- SHA-256: `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1`.
- [Direct asset](https://huggingface.co/facebook/dinov2-small/resolve/ed25f3a31f01632728cabb09d1542f84ab7b0056/model.safetensors).

For the DINO baseline, use a 224-pixel padded crop, retaining the animal's outline and coat
instead of cutting it off with a centre crop. Padding is our design choice, not a
paper result. Compare it against larger 336-pixel crops and document the exact
preprocessing. Never reuse embeddings across different preprocessing versions.

## What the research contributes

### DazzleCow: separate touching animals before identifying them

[Automated Re-Identification of Holstein-Friesian Cattle in Dense Crowds](https://arxiv.org/html/2602.15962v1)
combines OWLv2-large proposals, SAM2.1-large masks and a ResNet contrastive learner.
Simultaneously visible, distinct cows provide negative training examples. The
reported 98.93% is a box-matching measure, not end-to-end identity accuracy.
The reported 94.82 ± 4.10% re-identification accuracy uses seven training days,
one validation day and one test day: one camera, 19–24 cows per day, and a noon to
2pm recording window.

This supports careful animal isolation and using time to obtain useful training
constraints. It does not establish cross-farm, night, unknown-animal or online
enrollment performance. Large OWL/SAM models are more attractive for offline
annotation experiments than the default live path on a small computer.

The [code](https://github.com/Phoenix4582/DazzleCowIdentifier) is MIT-licensed.
No pretrained identity checkpoint or release was found in the repository. The
[project page](https://phoenix4582.github.io/dazzlecows.github.io/) did not expose
a dataset download when checked. Do not equate the paper's availability statement
with a verified downloadable dataset.

### MultiCamCows: collect different views of the same animal

[Holstein-Friesian Re-Identification using Multiple Cameras and Self-Supervision on a Working Farm](https://arxiv.org/html/2410.12695v2)
shows the value of combining camera views and the substantial variation between
individual cameras. Its recognition experiment is closed-set. A production
gallery should retain several confirmed appearances per cow, including different
views, rather than assume that one averaged vector covers every camera.

### OpenCowID: a future route to cattle-specific weights

[OpenCowID](https://openaccess.thecvf.com/content/WACV2026/papers/Prabhune_OpenCowID_Zero-Shot_Visual_Identification_of_Dairy_Cows_WACV_2026_paper.pdf)
investigates synthetic coat-pattern training for metric learning.
Its [MIT-licensed implementation](https://github.com/neis-lab/OpenCowID) includes
data generation and training, but no pretrained download was found in its README
or repository tree. Treat reproducing it as a separate experiment after the
frozen baseline exposes a measurable gap.

### Learning from a video is not the same as recognizing new cows

[Self-Supervised Animal Identification for Long Videos](https://arxiv.org/html/2601.09663v1)
uses frame-pair sampling, pretrained features and a small projection head. It is
interesting for inexpensive adaptation, but assumes a known, fixed population
within a video. Its final clustering uses that population count. A farm system
must allow a new animal to remain unknown; forcing every observation into a
known cluster would produce misleading identities.

## Model provenance and alternatives

| Model | What makes it useful | Decision |
| --- | --- | --- |
| DINOv2-small | Small, available official weights; general visual features; Apache-2.0 | Reproducible baseline; fresh camera-shift results are insufficient for useful default matching. |
| MegaDescriptor-T/S | Animal-specific embeddings and readily downloadable weights | Compare cached weights in this noncommercial trial; CC-BY-NC-4.0. |
| MIEWid | Strong multispecies retrieval method and promising historical local results | Compare cached weights on the same protocol; strongest current candidate. |
| DazzleCow / OpenCowID | Relevant cattle-specific training approaches | Follow-up experiments; not drop-in pretrained identity models. |

[MegaDescriptor-T](https://huggingface.co/BVRA/MegaDescriptor-T-224) and
[MegaDescriptor-S](https://huggingface.co/BVRA/MegaDescriptor-S-224) model cards
specify CC-BY-NC-4.0. This work is a noncommercial trial. Their README and config also
disagree about normalization: record the preprocessing actually evaluated.

[MIEWid's paper](https://arxiv.org/html/2412.05602v1) describes an EfficientNetV2
multispecies encoder, with useful retrieval and few-shot adaptation results.
The [official weights](https://huggingface.co/conservationxlabs/miewid-msv3) did
not specify a licence when checked. The rights holder's
[public report about the James Burgess mirror](https://huggingface.co/james-burgess/miewid/discussions/2)
states that the mirror's MIT claim was unauthorized. The mirror API returned
401 during this research. Record the actual cached checkpoint revision and
preprocessing in experiments; source-code and weights provenance are separate.
Cached comparisons proceed for this private noncommercial trial without making
licensing or farm-deployment claims.

## Evaluation data

Existing local datasets and embedding caches should be reused before downloading
large archives. Dataset licences and weight licences are separate.

| Dataset | Useful test | Published size and licence |
| --- | --- | --- |
| [SideViewCows2026](https://zenodo.org/records/21605650) | Parlor-to-barn/snapshot shift; 110 animals, 80,260 images with masks, right side only | 25.1 GB; snapshots 375.2 MB; CC-BY-4.0. |
| [MultiCamCows2024](https://data.bristol.ac.uk/data/en_GB/dataset/2inu67jru7a6821kkgehxg3cv2) | Held-out camera and day | 36.5 GiB; Non-Commercial Government Licence. |
| [OpenCows2020](https://data.bris.ac.uk/data/dataset/10m32xl88x2b61zlkkgz3fml17) | Small legacy regression; training overlap must be considered | 2.1 GiB; Non-Commercial Government Licence. |
| [8-Calves](https://huggingface.co/datasets/tonyFang04/8-calves) | Dense occlusion and identity continuity; eight calves in a one-hour sequence | Approximately 1.46 GB across image/video archives; CC-BY-4.0. |

SideViewCows is particularly useful because it provides separate environments
with consistent identities. Its author warns that adjacent frames are strongly
correlated. The eight-calves sequence tests difficult overlap, but eight animals
in one sequence cannot establish general performance across farms.

### What earlier local results do and do not show

Ignored local artifacts include previous MIEWid and MegaDescriptor experiments.
They are useful for choosing experiments, but they were not regenerated from this
branch and some datasets have already influenced earlier decisions. Treat them as
exploratory, not a fresh held-out benchmark.

The fresh DINOv2 baseline also gives a useful negative result: the exploratory
cross-camera evaluation produced poor precision at its calibrated threshold and
no accepted matches at a strict threshold. Small, permissively licensed weights
do not automatically make an effective cattle recognizer. The runnable evaluation
and its generated reports record exact counts. MIEWid and MegaDescriptor were
then compared with the same gallery and query manifest; see [BENCHMARK.md](BENCHMARK.md).

For example, the earlier MultiCam runtime reports contain a perfect constrained
assignment for 75 tracks and 25 known cows. The same reports' open enrollment
results create 59 clusters for those 25 cows. This exposes the difference between
an assignment with a known population and practical automatic enrollment.
Promising matching does not justify unattended gallery merging.

The local eight-calves MIEWid preprocessing experiment also rejects most
single-image queries at its chosen thresholds. Temporal samples improve coverage,
but only 24 grouped queries remain in that comparison. High accepted accuracy on
a small, heavily rejected sample must be accompanied by coverage and counts.

## Reproducible evaluation requirements

1. Save a versioned manifest before tuning. Split by recording/day, not adjacent
   frames. Keep gallery, threshold calibration and final evaluation separate.
2. Test one, three and five confirmed examples per cow. Hold out complete
   identities from the gallery to represent unknown animals.
3. Select similarity and runner-up margin thresholds on calibration only. Report
   accepted accuracy, wrong-ID rate, coverage, unknown false acceptance and raw
   counts together. Zero errors on a small sample is not a reliability guarantee.
4. Evaluate the actual production matcher, including rejection. Do not publish
   Hungarian assignments with a known cow count as online identification results.
5. Separate camera, day, viewpoint and farm conditions. Night/IR, solid-coated
   breeds and opposite-side matching remain unverified without appropriate data.
6. Measure runtime after warm-up, synchronize accelerator timing, and include
   preprocessing, memory and contention with behaviour detection.
7. Cache embeddings using image content, exact weight revision and preprocessing
   version. Changing a gallery or threshold should only rerun cheap matching.

## Farmer requirements and implementation priorities

**First useful workflow**

- Add a cow using its familiar name or ear-tag number and a clear sighting.
- Confirm several varied examples without exposing model settings.
- Show likely matches beside unknown sightings; allow confirm, correct and undo.
- Keep an unknown state for small, blurred, occluded or ambiguous animals.
- Store confirmed evidence separately from predictions. Never grow the reference
  gallery automatically from unconfirmed guesses.
- Keep processing local after the model download, with bounded review photos.

**Reliability and simplicity**

- Identity is optional. Isolating its failures from existing detections is a
  deployment requirement still to implement; the trial currently shares the
  detector process and its recovery policy.
- Sample a few useful crops per track instead of embedding every frame.
- Retain multiple appearances per cow; avoid treating left and right coat
  patterns as interchangeable without evidence.
- Recheck identity after tracking gaps rather than carrying a guess indefinitely.
- Flag conflicting simultaneous same-camera assignments instead of silently
  labelling two animals as the same cow.
- Use straightforward states and show the evidence image. A cosine score is not
  a calibrated probability and should not be displayed as certainty.

**Later, only when justified by measurements**

- Improve segmentation where overlapping animals contaminate identity crops.
- Compare a lightweight projection head or cattle-specific training against the
  frozen baseline on a fresh split.
- Evaluate local-feature verification for ambiguous shortlist candidates.
- Collect appropriately consented night, camera-change and new-farm evaluation
  data before claiming support for those conditions.

PyTorch's [MPS backend](https://developer.apple.com/metal/pytorch/) provides Apple
GPU acceleration. Actual model throughput and stability must be measured on the
available Mac; no cattle-specific MPS speed guarantee follows from backend
support alone.
