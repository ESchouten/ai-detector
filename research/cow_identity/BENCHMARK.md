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
