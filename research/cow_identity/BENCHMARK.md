# Cow identity baseline, 3 October 2026

**MIEWid is the useful research starting point. DINOv2 was faster but substantially less accurate. None of these results establish unattended farm identification reliability.** We used existing local public images and cached official checkpoints. No farm cameras, credentials, external AI services, training, or private uploads were used.

The subsequent [actual-policy video assessment](VIDEO_ASSESSMENT.md) is a necessary counterpoint: the crowded calf scene produced no accepted names with either tested detector. These cropped-image results must not be presented as the application's live recognition accuracy.

## Protocol

MultiCamCows2024: enroll from 14 August, query from 20 August 2023. The deterministic split contains 25 calibration cows (20 enrolled, 5 withheld unknowns) and 52 test cows (42 enrolled, 10 unknowns). No cow appears in both calibration and test. Three evenly spaced crops per camera are selected, giving 1,251 unique images. Exact duplicate content across partitions is rejected. `manifest.json` records every selected path, content hash and assignment.

For the primary representation comparison, each query is the normalized mean of three crop embeddings from one cow/day/camera. Identity scores use the best similarity among that cow's enrollment references. The runner-up must be a different cow, not a second reference for the winner. Similarity and margin thresholds are selected on calibration alone using a fixed 0.01 grid, maximizing correct coverage subject to zero observed false accepts. Rejecting everything is permitted. Test outcomes do not change these thresholds.

Two conditions are always reported:

- **All cameras:** enroll three views; query all three views six days later. Test: 126 known and 30 unknown observations.
- **Cross-camera:** enroll camera 1 only; query cameras 2 and 3 six days later. Test: 84 known and 20 unknown observations.

An observation is a cow/day/camera group, not an independently annotated encounter. Cameras and crops remain correlated. The gallery has 20 calibration identities but 42 test identities; transferring a threshold to a larger competing herd is deliberately not hidden. Foundation pretraining overlap is not fully auditable. This dataset has been explored before in this repository, so this is a development comparison, not a newly independent confirmation.

## Measured results

All-camera chronological test, with each model's calibration-only policy:

| Encoder | Correct / accepted | Known coverage | Rank-1 | Wrong known / unknown accepted |
| --- | ---: | ---: | ---: | ---: |
| DINOv2-small, 224 | 10 / 17 | 7.94% | 29.37% | 5 / 2 |
| DINOv2-small, 336 | 2 / 2 | 1.59% | 39.68% | 0 / 0 |
| MegaDescriptor-S, 224 | 11 / 11 | 8.73% | 76.19% | 0 / 0 |
| MIEWid v3, 440 | 88 / 89 | 69.84% | 92.06% | 0 / 1 |

Strict cross-camera chronological test:

| Encoder | Correct / accepted | Known coverage | Rank-1 | Wrong known / unknown accepted |
| --- | ---: | ---: | ---: | ---: |
| DINOv2-small, 224 | 0 / 0 | 0% | 28.57% | 0 / 0 |
| DINOv2-small, 336 | 1 / 4 | 1.19% | 19.05% | 3 / 0 |
| MegaDescriptor-S, 224 | 4 / 4 | 4.76% | 59.52% | 0 / 0 |
| MIEWid v3, 440 | 37 / 44 | 44.05% | 72.62% | 3 / 4 |

Zero errors with two or four accepted observations says little about reliability. MIEWid's cross-camera errors show why enrollment needs several useful views and why the application should retain an unknown state instead of forcing a name.

## Speed and cache replay

Actual Metal/MPS FP32 inference on the development Mac, including image decoding and per-image cache writes but excluding checkpoint loading/download. These are batched throughput numbers, not single-cow latency, and exclude detection/tracking:

| Encoder | Batch | Images | Measured inference | Per image |
| --- | ---: | ---: | ---: | ---: |
| DINOv2-small 224 | 16 | 1,251 | 8.96 s | 7.2 ms |
| DINOv2-small 336 | 16 | 1,251 | 16.04 s | 12.8 ms |
| MegaDescriptor-S 224 | 16 | 1,251 | 11.70 s | 9.4 ms |
| MIEWid v3 440 | 8 | 1,251 | 27.21 s | 21.7 ms |

Each warm replay reproduced the complete baseline result dictionaries exactly with **zero new inferences**, without importing torch or decoding images. Cache keys include image SHA-256, model/weight/preprocessing fingerprint, resolution, precision, device and library versions. Raw source images, tensors and checkpoints remain ignored; compact reports and the split manifest are retained under `results/2026-10-03/`.

## Exploratory improvements

These controls were added after the baseline results were inspected; they are explicitly exploratory. `ablation.py` fits a fixed 50% shrinkage covariance transform using within-cow/camera differences in enrollment images only. It transforms and normalizes each query crop before pooling. Neither query images nor unknown cows fit the transform; every condition recalibrates on the calibration cows only. No fine-tuning or parameter search over shrinkage is used.

| MIEWid variant | All-camera correct / accepted | Known coverage | Cross-camera correct / accepted | Known coverage |
| --- | ---: | ---: | ---: | ---: |
| Raw, pooled crops | 88 / 89 | 69.84% | 37 / 44 | 44.05% |
| Gallery adaptation, pooled crops | 101 / 102 | 80.16% | 58 / 63 | 69.05% |
| Raw, three samples must agree | 83 / 86 | 65.87% | 18 / 18 | 21.43% |
| Adapted, three samples must agree | 83 / 84 | 65.87% | 29 / 29 | 34.52% |

Gallery adaptation is promising but remains a research control. The three-sample test checks agreement across the three selected images, **not** production tracker association or a real five-second confirmation window. It must not be described as a completed end-to-end validation of the application.

We also measured fixed raw-MIEWid policies requested during implementation:

| Similarity / margin | Pooled multiview correct / accepted | Three-sample agreement correct / accepted |
| --- | ---: | ---: |
| 0.90 / 0.08 | 0 / 0 | 0 / 0 |
| 0.65 / 0.10 | 55 / 55 | 12 / 12 |
| 0.65 / 0.08 | 68 / 68 | 12 / 12 |

The 0.90 threshold is unusably strict for this model. The lower fixed thresholds avoid observed mistakes here, but accept few groups when all three individually must pass. A threshold is not a probability or a farm-independent assurance. The complete calibration, per-camera and fixed-policy results are in `miewid440-ablation.json`.

## Reproduce

Install an isolated environment from `requirements.txt` (Python 3.12). The measured run used torch 2.11.0 and transformers 4.57.6. The application's own environment can run the scripts too; differing library versions correctly produce different cache fingerprints.

```sh
uv venv --python 3.12 /tmp/cow-identity-eval
uv pip install --python /tmp/cow-identity-eval/bin/python -r research/cow_identity/requirements.txt

/tmp/cow-identity-eval/bin/python research/cow_identity/benchmark.py \
  --dataset /path/to/MultiCamCows2024Root \
  --output .cache/cow-identity-runs/dino224 --device mps

# MIEWid uses an explicitly supplied local official checkpoint; no remote code.
/tmp/cow-identity-eval/bin/python research/cow_identity/benchmark.py \
  --dataset /path/to/MultiCamCows2024Root \
  --output .cache/cow-identity-runs/miewid440 --model miewid \
  --weights /path/to/model.safetensors --image-size 440 --batch-size 8 --device mps

# Same command plus --replay needs only recorded manifest/encoder and the cache.
/tmp/cow-identity-eval/bin/python research/cow_identity/benchmark.py \
  --dataset /path/to/MultiCamCows2024Root \
  --output .cache/cow-identity-runs/miewid440 --model miewid --image-size 440 --replay

/tmp/cow-identity-eval/bin/python research/cow_identity/ablation.py .cache/cow-identity-runs/miewid440
/tmp/cow-identity-eval/bin/python -m unittest discover -s research/cow_identity -p 'test_*.py'
```

MegaDescriptor uses `--model megadescriptor --image-size 224 --weights /path/to/pytorch_model.bin`. Both comparison checkpoints are verified against pinned SHA-256 digests; the MegaDescriptor loader uses tensor-only `weights_only=True`, while MIEWid uses safetensors. Model and dataset provenance is in `sources.json`. Code never enumerates or calls real camera sources.

## Next validation gates

1. Confirm enrollment samples and cow names with the farmer; never promote an unreviewed prediction into ground truth.
2. Evaluate actual tracks from held-out full video, including crowded and partially visible cows, night/IR footage and camera disconnects. Report false names per cow-hour and identity switches, not only retrieval rank-1.
3. Collect a new farm cohort with independent manual labels. Separate enrollment, calibration and test by physical passage and day; freeze thresholds before opening test labels.
4. Measure single-crop latency, memory and total camera/detector/identity throughput together on the target Mac/Windows hardware.
5. Expand gallery-only adaptation only if it helps the real production decision rule. Existing small fine-tuning trials did not improve the incumbent; do not begin a large training project without an identified failure mode and a new held-out panel.

## Production integration smoke

`smoke_runtime.py` additionally runs the actual production MIEWid encoder, `GalleryIdentifier`, SQLite embedding cache, catalog and live-preview publisher on the first 30 seconds of the public 8-calves video at 1 fps. A cached standard YOLO26m-seg model supplies cow boxes and ByteTrack IDs. Everything runs locally on MPS. The initial gallery is empty. After three observations, two first-frame examples are enrolled from publisher annotations for dataset calves 1 and 3; predicted identities never supply enrollment truth.

The safe numeric annotation archive names and hashes its original publisher pickle. The script verifies that hash and reads the numeric archive with `allow_pickle=False`; it never executes the pickle. Recorded source and model hashes make the input selection auditable.

The run produced 153 tracked cow boxes, retained five review crops before enrollment and 33 sightings overall. Four box observations received a named suggestion; 149 remained unknown. **These counts are not accuracy metrics.** Enrollment and query observations come from the same short clip, only two cows are enrolled, and predictions were not scored against complete annotation tracks.

Verified integration contracts:

- Production and reviewed research MIEWid encoders produced exactly equal vectors for the two annotated crops on the current runtime: 2,152 dimensions, finite values and unit norm.
- Re-reading already cached gallery images required zero additional encoder calls and returned identical vectors.
- Identity processing preserved the original detection coordinates.
- The real live-preview JSON contained `id`, `name` and `similarity` for cow boxes.
- Predictions left the explicitly seeded catalog unchanged.

The runtime used torch 2.12.1, torchvision 0.27.1, timm 1.0.30 and Ultralytics 8.4.80. This parity check tests the same architecture under the current library versions, not bit-for-bit reproduction of the older benchmark environment. The compact result is `results/2026-10-03/runtime-smoke.json`; generated crops and video frames remain ignored.

Run in the application's Python environment, with a fresh output directory:

```sh
ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS=1 detector/.venv/bin/python research/cow_identity/smoke_runtime.py \
  --video datasets/8-calves/video/pmfeed_4_3_16.mp4 \
  --annotations datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz \
  --source-pickle datasets/8-calves/video/pmfeed_4_3_16.pkl \
  --detector detector/yolo26m-seg.pt --weights /path/to/official/miewid/model.safetensors \
  --output .cache/cow-identity-runtime-smoke/new-run --device mps
```

## Frozen encoder packaging

`frozen_smoke.py` is a minimal PyInstaller entry point importing both production encoders. A macOS arm64 one-directory build completed in 115 seconds and occupied 717 MB uncompressed. The actual frozen executable successfully encoded one public MultiCamCows crop with each model on MPS: DINOv2 returned 384 dimensions and MIEWid 2,152, both finite and unit-normalized. Cached, hash-verified weights were used with `HF_HUB_OFFLINE=1`. The recorded result is `results/2026-10-03/frozen-smoke.json`.

The check covers the explicit DINOv2 model import, timm's EfficientNet registration, dependency metadata and the native Torch/Metal resources needed by these encoders. Keep the existing `--copy-metadata=timm` and `--copy-metadata=transformers` distribution flags. In particular, transformers 4.57.6's hook checks an older timm version range and does not collect metadata for the installed timm 1.0.30 automatically. No extra collection flags were needed in this run.

This verifies an encoder executable, **not the full installer or Windows packaging**. The size is not an estimate of the additional application download: much of Torch and its dependencies is already part of the detector.

```sh
PYINSTALLER_CONFIG_DIR=/tmp/cow-identity-pyinstaller detector/.venv/bin/python -m PyInstaller \
  research/cow_identity/frozen_smoke.py --name identity-encoders-smoke --onedir \
  --paths detector/src --copy-metadata=timm --copy-metadata=transformers \
  --distpath /tmp/cow-identity-frozen/dist --workpath /tmp/cow-identity-frozen/build \
  --specpath /tmp/cow-identity-frozen --noconfirm

HF_HUB_OFFLINE=1 /tmp/cow-identity-frozen/dist/identity-encoders-smoke/identity-encoders-smoke \
  --cache .cache/cow-identity/models --weights /path/to/official/miewid/model.safetensors \
  --crop /path/to/public/cow-crop.jpg --output /tmp/cow-identity-frozen-result.json --device mps
```

## Video recognition development, after the integration assessment

The initial three-reference calf-video result exposed a substantial gap between
image retrieval and useful video identification. A second development panel now
isolates recognition with publisher boxes and track IDs. It uses early 0–299 s
for enrollment candidates, 330–629 s and 930–1229 s for development, and
1230–1529 s for calibration. Calves 7 and 8 never enter enrollment or adaptation.
The later 1800–2099 s and 2700–2999 s windows remain reserved for a separately
frozen final policy. `recognition_protocol.json` records the design.

These identity scores assume that the publisher's `tracklet_id` field retains
biological identity across the sampled windows. An independent annotation audit
verified coordinates and reviewed chronological movement; it did not support a
suspected switch between IDs 5 and 8. This bounded review cannot certify every
identity throughout the video. The scores remain conditional on those labels.

We cached 7,550 MIEWid vectors in 151.8 seconds on MPS, reusing 671 previously
encoded crops. Each selection uses at most ten confirmed images per enrolled
calf. Diversity selection starts from a medoid and then selects distant examples
from the early candidate set; it does not use query images. The publisher labels
simulate a human confirming which calf a reference depicts. This research does
not establish that the application can generate a correct enrollment track
without human review.

| Recognition-only control | Development coverage | Later development coverage | Precision, respectively |
| --- | ---: | ---: | ---: |
| Ten diverse references, five-frame mean descriptor | 28.7% | 37.8% | 98.66%, 99.41% |
| Same, gallery covariance adaptation, three-frame mean | 24.4% | 25.0% | 99.77%, 99.56% |
| Four gallery orientations, five-frame mean | 28.9% | 38.0% | 100%, 97.43% |
| Three confirmations, 30 s name persistence, no geometry gate | 50.3% | 52.6% | 100%, 99.37% |
| EMA 0.2, overlap gate 0.5 for new evidence, 60 s persistence | 51.5% | 51.4% | 100%, 100% |

Thresholds and margins were selected only on calibration, maximizing coverage
subject to at least 99% observed precision and at most 1% unknown false names.
These development comparisons informed further choices; they are not independent
final confirmations. The 30 s persistence control has six false names among 598
unknown observations in the later window, narrowly exceeding the 1% target.
The last row had no observed false names in either development window, but its
coverage remains below the 60% target. All these controls use oracle tracks.

The main failure is representation rather than reference count alone. Calf 5
has 55 usable early candidates, yet only 7% rank-1 retrieval on calibration
under the first control. A reviewed contact sheet shows large orientation and
viewpoint changes. Gallery-only ridge projections and orientation augmentation
did not solve the problem. Covariance adaptation remains experimental, and a
larger gallery is not a substitute for reliable representations and tracking.

`recognition_temporal.py` separates tracker IDs from truth labels, rejects
duplicate simultaneous names, resets contradictory evidence and track gaps,
and never confirms untracked boxes. Geometry gates admission of new evidence;
an existing identity may survive a bounded period without new evidence. This is
a research policy for subsequent evaluation with real detector tracks, not a
validated change to the runtime.

A bounded MIEWid fine-tuning experiment then used exactly the 60 selected early
photos. Fifteen epochs updated only the final EfficientNet block and convolution
head, with frozen batch-normalization statistics and rotation/color/crop
augmentation. Training plus two sparse evaluation snapshots took 116 seconds on
MPS. It did not provide a useful gain: on identical five-second query samples,
baseline rank-1 was 70.0%/76.3%, versus 70.3%/78.0% after fifteen epochs. At the
required calibration precision, coverage fell to 8.9%/13.6%. Neither checkpoint
was promoted. `recognition/fine-tune.json` records the controls and results.

Compact results and selected-reference provenance are under
`results/2026-10-03/recognition/`. Feature arrays and images remain in ignored
`.cache/cow-recognition-development`. To reproduce the CPU comparisons after
running `recognition_features.py` with the source video, safe annotations and
official weights:

```sh
detector/.venv/bin/python research/cow_identity/recognition_experiment.py .cache/cow-recognition-development
detector/.venv/bin/python research/cow_identity/recognition_projection.py .cache/cow-recognition-development
detector/.venv/bin/python research/cow_identity/recognition_temporal.py .cache/cow-recognition-development
```

The projection comparison additionally needs `recognition_rotations.py` to cache
the gallery orientations once. None of these scripts reads the reserved final
windows.

## Public-cattle adaptation and transfer

To avoid fitting only six calves, we prepared 3,033 training crops from 219 public
identities: 139 from Cows2021 and 80 from SideViewCows2026. Validation contains 53
different identities, with enrollment on earlier days and queries on later days;
nine validation identities are never enrolled. All 8-calves and ETHZ material is
excluded from training. `cattle_training_protocol.md` records source selection
and the deliberate repurposing of Cows2021's labeled identification split.

Caching the 3,778 training and validation descriptors took 89.8 seconds on MPS.
A small 2,152→512→256 metric head was then trained on CPU with contrastive and
cosine-classification losses. Only external validation selected its checkpoint
and blend with the original descriptor. The selected ten-epoch head contributed
25% of cosine similarity; no transfer-video result selected that checkpoint.

| External validation selection panel | Correct names | Named precision | Known coverage | Unknown false names |
| --- | ---: | ---: | ---: | ---: |
| Original MIEWid | 257 | 99.61% | 82.90% | 1 / 117 |
| Selected public-cattle head | 261 | 99.62% | 84.19% | 1 / 117 |

This small gain **did not transfer reliably**. With the same ten confirmed calf
references and five-frame pooling, development coverage fell from 28.7%/37.8%
to 25.9%/36.2%. The actual detector/tracker evaluation reached 18.3% coverage but
only 91.9% named precision. On the adult ETHZ later-day and night panels, rank-1
retrieval fell from 32.0%/43.4% to 31.0%/40.9%; neither version named any cow there
at the fixed 0.65 similarity / 0.10 margin. The head is not promoted.

`recognition_public_features.py`, `recognition_public_head.py` and
`recognition_public_transfer.py` reproduce the extraction, selection and cached
transfer. `recognition/public-head.json` records the results and exact hashes.
The external validation figures are model-selection evidence, not a final
generalization estimate. The source model's pretraining identity overlap is not
fully auditable. No weights or image datasets are committed.

A subsequent, bounded full-backbone pilot used the same external cohort: 200
contrastive/classification steps, eight images per batch with distinct-day
positives, frozen batch-normalization statistics and gradient checkpointing.
The protocol and seed were recorded before training. Training plus two validation
snapshots took 255 seconds on MPS. External validation selected step 200, raising
known coverage from 82.90% to 90.32% at 99.64% precision, with one false name among
117 unknown observations. This is a useful optimization result on that selection
panel, not proof of farm-to-farm generalization.

Transfer again failed the goal. With the original ten calf reference photos,
later development coverage rose to 37.9%, but precision fell to 88.9% and 13 of
119 unknown observations received names. On ETHZ's later-day/night panels,
rank-1 retrieval improved modestly to 35.5%/47.9%; the frozen external threshold
still named only 9.0%/1.4% of known observations, with night precision 66.7%.
The adapted checkpoint remains research-only. `recognition_public_finetune.py`
and `recognition_archive.py` reproduce training and transfer; the complete
selection and transfer results are in `recognition/public-backbone.json`.

## Larger MegaDescriptor control

We also tested pinned MegaDescriptor-B-224 weights on the same early enrollment
and every fifth second of the development/calibration video panels. The publisher
provides conflicting preprocessing examples: its machine-readable timm config
uses a central crop, while its [actual inference notebook](https://github.com/WildlifeDatasets/wildlife-tools/blob/main/baselines/inference/MegaDescriptor-B-224.ipynb)
stretches the entire image to 224×224. Both use ImageNet normalization. We tested
both recipes with separate cache fingerprints rather than silently changing the
earlier MegaDescriptor-S baseline.

Neither solves this scene. With the same diverse reference photos as MIEWid, the
center-crop model reaches 62.5%/57.9% rank-1 retrieval versus MIEWid's
70.0%/76.3% on the identical sparse queries. The full-crop recipe reaches
38.6%/54.3%; allowing that encoder to select its own ten diverse references raises
this to 53.9%/68.0%, but accepted coverage remains 3.1%/3.1% with only 84.6%
precision. No MegaDescriptor variant is promoted.

Each control encoded 1,798 crops in about 190 seconds using two CPU threads while
other research work ran concurrently. This is not a Metal speed comparison.
`recognition_compare.py` reproduces the common-query, fixed-reference comparison
from cached arrays; `recognition/megab.json` preserves all conditions and hashes.
The larger encoder offers no measured reason to replace MIEWid here.

A source review also considered MegaDescriptor-L-384, without downloading or
evaluating it. The authors' [model-size ablation](https://openaccess.thecvf.com/content/WACV2024/supplemental/Cermak_WildlifeDatasets_An_Open-Source_WACV_2024_supplemental.pdf)
does not show a consistent cattle-specific advantage over the base model:
Cows2021 improves from 99.37% to 99.54%, while FriesianCattle2017 falls from
97.47% to 96.46%. Their [evaluation recipe](https://wildlifedatasets.github.io/wildlife-tools/megadescriptor/)
also uses known identities represented in training and excludes unknown ones;
these results cannot establish open-set performance on this video. Given the
negative base-model control, foreground quality and confirmed reference coverage
remain the next experiment. This is a prioritization decision, not evidence
that the untested large model would fail.

## Additional confirmations

`recognition_enrollment_protocol.json` freezes a separate active-enrollment arm.
The already exposed 330–629 s window is explicitly repurposed for asking up to
18 additional questions. Every 15 seconds, the selector may offer a sufficiently
clear, uncertain crop; it sees embeddings and geometry before a simulated human
response reveals the publisher identity. It counts unknown responses and repeat
requests. At most two new references per known cow replace redundant original
references, keeping the gallery at ten per cow. Evaluation starts at 930 s;
calibration remains 1230–1529 s and the reserved final windows remain unopened.

The cost is substantial: the raw/masked controls used all 18 questions, of which
8–13 concerned unenrolled calves. Only 5–9 new references were added. This is a
perfect-human-response, oracle-box experiment, not a claim that those questions
will be equally easy for a farmer. Suppressing repeat reviews using actual
tracker IDs still needs testing; publisher identity was not used to hide them.

With masked crops and the original diverse gallery, later development precision
improved from 97.96% to 99.32%, but coverage only from 40.1% to 40.7%. Fixed 50/50
fusion of raw and masked descriptors raises rank-1 retrieval to 91.1% after the
same enrollment policy, including 95% rank-1 for calf 5. Acceptance remains only
42.6% coverage at 98.71% precision, with two false names among 119 unknown
observations. These sparse five-second samples do not establish live temporal
performance, and neither control meets the goal.

The scripts `recognition_enrollment.py` and `recognition_fusion.py` use only
cached features. Results and every simulated question are recorded in
`recognition/active-enrollment.json` and `recognition/active-enrollment-fused.json`.

The same question policy was then applied to **actual detector crops**, preserving
every prediction and using its matched publisher label only after selection. Raw
features asked 16 questions and added six references; masked/fused features added
seven after 17/16 questions. Unmatched detections, unknown cows and already-filled
reference slots count as unsuccessful requests. `recognition_tracked_enrollment.py`
records each response and reconstructs selected descriptors from hashed source
archives; the query evaluator refuses to score the enrollment window again.

The raw control improves actual later-window coverage only from 10.9% to 13.1%,
while conservative precision falls from 97.0% to 95.9%. Naming an unmatched box
counts as incorrect in this precision bound; its true identity is not assumed.
After their additional confirmations, masked/fused representations reach only
9.2%/11.0% coverage at 97.6%/96.6% conservative precision. Their unknown false
names are one/four among 598 unknown observations. None is promoted.
Before extra confirmations, raw/masked fusion using the exact original reference
photos gives only 9.1% coverage at 89.1% conservative precision on the earlier
window. The strong oracle rank-1 result therefore has not translated into a
usable live naming system. `tracked/active-enrollment.json` and
`tracked/mixed-fusion-fixed-gallery.json` preserve these controls.

## Masked farm adaptation with public replay

A separate 200-step pilot updated the full backbone using the same 60 early
confirmed photos with SAM foreground masking, alongside the public-cattle cohort.
Each batch contained two calf identities and two public identities, with two
different photos per identity. Classifier prototypes used training descriptors
only; validation identities, unknown calves and all calf frames after 299 s were
excluded from training. `recognition_farm_training_protocol.json` was frozen and
independently reviewed before the run. Training and external validation took
249 seconds on MPS.

The baseline and both checkpoints were compared on the same masked reference
photos and 2,526 actual calibration detections. Checkpoint selection required
the external validation coverage to retain at least 95% of its baseline, with
99% named precision and at most 1% unknown false names. It then maximized correct
calibration names under the same precision/unknown requirements, preferring the
original model on ties. Both adapted checkpoints passed the external guard, but
calibration coverage fell from 9.84% to 2.45% after 100 steps and 2.28% after 200.
The original weights therefore remain selected. Their frozen policy reaches
9.08% later-window coverage and 97.60% conservative precision. No adapted model
was run on development or final windows after it failed calibration.

`recognition_farm_data.py` verifies the exact training photos;
`recognition_public_finetune.py --enrollment` runs the bounded replay experiment;
`recognition_farm_select.py` applies the frozen guard. The full negative result,
including every calibration condition, is in `recognition/farm-backbone.json`.

The failed end-to-end selection does **not** mean that training made the embedding
worse. A subsequent calibration-only loss audit used the original model's fixed
policy for every checkpoint (EMA 0.5, similarity 0.55, margin 0.20, three accepted
observations, no retained name without current evidence). Correct matched names
passed through these stages:

| Stage | Original model | Step 100 | Step 200 |
| --- | ---: | ---: | ---: |
| Raw nearest identity, before rejection | 1,255 | 1,317 | 1,340 |
| Smoothed nearest identity, before rejection | 1,266 | 1,332 | 1,353 |
| Similarity and margin accepted | 204 | 292 | 369 |
| Three-observation agreement | 177 | 264 | 334 |
| After confirmed-name collisions | 177 | 264 | 334 |

The denominator is 1,799 visible known-cow observations. Agreement produces no
wrong names on matched known or unknown cows in this fixed-policy control, but
names 0, 16 and 21 unmatched predictions. Those remain errors in the conservative
precision bound. They are all proposed names for calf 4: three independently
inspected samples visibly contain that calf but miss the IoU 0.5 boundary, while
two other cases duplicate an existing prediction. The remaining observations
have not been individually certified. This is an annotation/extent diagnostic,
not permission to count every unmatched name as correct.

The largest measured rejection is confidence separation, not collision handling.
Raw candidate collision rejection would remove only six correct step-200 names;
confirmed collisions remove none. A 0.5 overlap gate reduces step-200 correct
names from 334 to 220, and a 0.2 gate to 21. Better tracking remains useful, but
changing name assignment alone cannot explain or recover the missing coverage.

A frozen, label-free control tightened **every** predicted rectangle to the
foreground retained in its cached SAM image. Features, naming and track IDs
stayed unchanged, and every rectangle was associated again using the same
one-to-one IoU 0.5 rule. Matched rectangles increase from 2,220 to 2,260. Step 200
changes from 334 correct/21 unmatched names to 343 correct/12 unmatched names,
still only 19.07% coverage at 96.62% conservative precision. The original model
loses two correct names under tightening. Therefore this is not promoted.
The foreground was reconstructed from lossless pixels differing from gray 127;
a production study would retain the actual binary masks and new provenance.

Visual and numerical checks identify a persistent enrollment gap for calf 5:
most early reference photos show a compact lying or oblique body, whereas later
queries show an elongated standing or end-on body. Its matched raw rank-1 result
is only 2.8% before adaptation and 9.1% afterwards. Calf 6 improves from 60.1%
to 88.8%, but many correct similarities and margins still fall below the fixed
acceptance thresholds. These small, changing views need stronger evidence or
more useful confirmed poses; a lower threshold alone would not establish safe
recognition of unknown cows.

`recognition_diagnostics.py` reproduces the stage audit and all-box extent
control without inference. `recognition/farm-diagnostics.json` includes its
frozen control, source hashes and all conditions. The original benchmark,
checkpoint selection and reserved final windows remain unchanged.
