# Anatomy-aligned coat barcodes: bounded feasibility review

This is a source and metadata review on 3 October 2026, not a model experiment.
No weights, datasets or environments were downloaded or installed; no model ran.
The source/metadata inventory is recorded in
[`autocattlogger-feasibility.json`](results/2026-10-03/recognition/autocattlogger-feasibility.json).

**Recommendation:** retain one pose-only feasibility experiment as a materially
different hypothesis. Do not import the complete AutoCattlogger application into
the detector. A learned anatomical coordinate system could remove pose variation
that the failed global descriptors, principal-axis rotation and generic local
matching did not remove. This is most plausible for a fixed overhead passage
camera with the animal's back in view; it is not evidence for arbitrary barn views.

## What is different, and what is not established

The published method builds a 2,048-bit coat representation from an anatomically
rectified image. A closed track contributes the mode of its most central 20% of
eligible photographs. Track recognition aggregates predictions over the track;
this is not an immediate online guarantee. Its reported track top-one accuracies
are 95.27%, 92.59% and 91.25% across the three comparisons. Evaluation concerns
common cows and usable barcodes, and treats indistinguishable fully black cows
specially. It does not establish our all-visible denominator, 99% named precision
or rejection of previously unseen cows. The paper also retains human ear-number
records for attaching external names; barcode enrollment and ear reading are
different tasks. [Paper](https://doi.org/10.1016/j.atech.2025.101561).

The author's ten landmarks are left/right shoulder, withers, center back,
left/right hip bone, hip connector, left/right pin bone and tail head. The warp
uses 16 corresponding triangles, orients withers toward the top and tail toward
the bottom, and produces a 512×256 image. This supplies named body correspondence
and resolves the 180-degree ambiguity retained by our principal-axis control.
The implementation can interpolate missing landmarks; accepting a plausible
shape is not proof that a hidden body part was observed.
[Landmarks](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/configs/mmpose_configs/metadata_config/cow_tv_keypoints.py),
[warp](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/autoCattlogger/helpers/helper_for_morph.py).

The barcode code resizes to 512×1024, thresholds block averages and uses nearest
Hamming matching. It does not provide an open-set rejection policy. A near-uniform
coat can share a representation with another animal; automatic profile merging
must remain unresolved in that case. These differences make this a distinct
control from [foreground/local matching](SEGMENTATION_STUDY.md) and the failed
[temporal projection](TEMPORAL_PROJECTION_PILOT.md), not grounds to weaken their
metrics or recycle their thresholds.
[Barcode implementation](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/autoCattlogger/helpers/helper_for_QR_and_inference.py).

## Available assets and practical barriers

The inspected repository revision is
`d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044` (Apache-2.0). Public Box page metadata
advertises both checkpoints with downloads enabled:

| Checkpoint | Advertised bytes | Availability evidence |
|---|---:|---|
| HRNet `epoch_210_kpDatasetV5_2024.pth` | 768,697,571 | [Public file page](https://app.box.com/s/0lh7opyprerc10rhw660bealryyltumq) |
| MaskRCNN `maskRCNN_kpDatasetv6_orbbec2025_model_final.pth` | 280,289,315 | [Public file page](https://app.box.com/s/aa8cu8cv0pszhj64446yiim9dtpkjs6h) |

The README's static-download HEAD requests returned 404, while the public file
pages returned metadata successfully. Therefore weights are advertised, but a
successful binary transfer, checkpoint contents and SHA256 remain unverified.
The HRNet filename says V5/2024 while surrounding configuration comments mention
V6/Orbbec2025: inspect the checkpoint's own metadata before assuming its exact
training provenance. File size is not a measured inference-memory requirement.
[Author model instructions](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/models/readme.md).

The public data include the two-day cut videos already used by our Purdue
regressions, plus 460 training and 34 test images with pose/mask annotations. The
author explicitly describes the training archive as a reduced subset of the
released model's training set. This review found no newly protected cross-day
test. Existing June8/June9 outcomes remain exposed; the closed 8-Calves interval
at 3000 seconds and later was not accessed.
[Data instructions](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/data/readme.md).

## Smallest plausible implementation boundary

The full application eagerly imports Detectron2 and MMPose, and its automatic
device choice is CUDA or CPU. The documented setup supplies a CUDA container or
a 5.2 GB environment; it is not a tested MPS integration.
[Application](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/autoCattlogger/autoCattlogger.py),
[setup](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/setup/readme.md).

We already have masks and camera continuity. A narrow candidate would add only
the published top-down HRNet-W48 heatmap model and CPU coordinate decoding/warp.
Its configured input is 192×256, output 10×48×64; preprocessing uses UDP affine
coordinates, RGB normalization and flipped-heatmap testing. Those details must
survive any conversion, particularly left/right landmark swaps.
[Exact configuration](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/configs/mmpose_configs/trainer_config/td-hm_hrnet-w48_udp-8xb32-210e_coco-256x192_cow-tv_orbbecCam2025.py).

The selected HRNet and simple heatmap head use ordinary convolution,
normalization and interpolation, which makes isolated MPS inference plausible.
However, the pinned MMPose package eagerly imports EDPose, which imports
`mmcv.ops.MultiScaleDeformableAttention`. Installing `mmcv-lite` alone is not a
demonstrated import solution. The original official HRNet pose model is a small
PyTorch-only source module (MIT), so reusing that pinned implementation with an
explicit state-key conversion is an alternative worth checking. Neither state
compatibility nor numerical equivalence has been tested. Do not silently load
partial weights or substitute a human-pose checkpoint.
[Pinned MMPose head imports](https://github.com/open-mmlab/mmpose/blob/759b39c13fea6ba094afc1fa932f51dc1b11cbf9/mmpose/models/heads/transformer_heads/edpose_head.py),
[official HRNet model](https://github.com/leoxiaobin/deep-high-resolution-net.pytorch/blob/6f69e4676ad8d43d0d61b64b1b9726f0c369e7b1/lib/models/pose_hrnet.py).

The next bounded step should first obtain and hash only the pose checkpoint,
check all tensor keys/shapes and provenance, then prove a small fixed CPU/MPS
heatmap/coordinate comparison with exact preprocessing. Stop if this requires a
framework overhaul or cannot preserve the author model. Only after that should
one frozen passage comparison test anatomy-aligned barcodes against the existing
unaligned control, keeping misses, partial animals and unknown cows visible in
the score. Pose quality and identity matching should be measured separately.

For the farmer workflow, complete qualified passages may create provisional
anonymous profiles automatically. A later passage must either obtain supported
same-animal evidence or remain separate; nearest top-one alone must not merge
profiles. Ear numbers may annotate only the supported episode, independently of
coat matching. No manual seed identity is required for that workflow, but this
review has not supplied the missing cross-visit acceptance evidence.
