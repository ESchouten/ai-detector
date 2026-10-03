# Published pose artifact: safe loading and topology

The bounded follow-up downloaded only the author-published HRNet checkpoint:
768,697,571 bytes in 40.5 seconds. The normal public Box URL works without the
`.pth` suffix in the README. SHA256 is
`a23cfd37a78a0745392e5b0457dd468e9afbea3eebbbf19b94d32b988734438f`;
its SHA1 matches the public file metadata. Provenance, every tensor shape and
source hashes are in
[`autocattlogger-checkpoint.json`](results/2026-10-03/recognition/autocattlogger-checkpoint.json).
The artifact phase downloaded no MaskRCNN, dataset or framework environment and
ran no forward pass. The subsequent isolated CPU reference proof is recorded below.

## Artifact identity and safe extraction

Passive `pickletools` inspection finds epoch210, iteration37590 and a saved
configuration naming `kp_dataset_v5`, with experiment
`cow-tv_openBarn2024_20250416_211851` and recorded time `20250416_225810`.
The ten landmarks and HRNet-W48/UDP192×256 configuration agree with the filename.
The surrounding repository's V6/Orbbec2025 comments must not override this V5
artifact. This is the checkpoint's self-reported provenance, not an independent
audit of the original training data.

The complete training checkpoint was refused by `torch.load(weights_only=True)`:
its metadata includes NumPy and MMEngine training-history constructors. No
allowlisted globals, unrestricted load or metadata execution was used.
[`autocattlogger_checkpoint.py`](autocattlogger_checkpoint.py) accepts exactly
the SHA256 above. It verifies the state dictionary's byte boundaries, every memo
dependency, four permitted Torch/OrderedDict globals and all1754 storage lengths.
Only one earlier memo is referenced: the empty string, verified directly in the
original pickle. That reference is replaced with the same literal value; every
other state opcode and referenced storage byte is preserved. The new state-only
archive contains254,702,280 storage bytes and loads with `weights_only=True` and
no extra globals.

The first extraction prefix used a harmless pickle POP that the restricted
PyTorch scanner does not implement. It failed before tensor loading. Its
[diagnostic source](results/2026-10-03/recognition/autocattlogger-extraction-first-attempt.py)
and [failure record](results/2026-10-03/recognition/autocattlogger-extraction-first-attempt.json)
are preserved as a rejected attempt, not an alternative extractor.

## Existing timm reuse

Installed timm1.0.30 already has every required backbone tensor name and shape.
Its feature backbone additionally computes three low-resolution outputs at the
last fusion module. The author configuration requests only the high-resolution
output. Removing those three unused output-fusion branches removes78 extra
tensors; none of the four input branches is removed.

The resulting backbone loads all1752 tensors strictly. A48→10,1×1 convolution
loads both head tensors strictly. All1754 loaded tensors equal their extracted
source tensors, and the combined model has63,595,402 parameters. This is a
key/shape/loading audit only. It does **not** establish numerical equivalence to
the author's forward implementation, valid pose estimates, or cattle recognition.
The wrong-artifact rejection test passes; Ruff is clean.

## Completed isolated author CPU reference

The separately approved reference proof passed, using the actual saved V5
configuration and the author's pinned MMPose source at
`759b39c13fea6ba094afc1fa932f51dc1b11cbf9`. Exact input/source/dependency hashes and
tolerances were frozen in
[`autocattlogger_reference_protocol.json`](autocattlogger_reference_protocol.json)
(SHA256 `36475a8284c67494cd7f5a2512ed0aaa92c8cee6808375293901ad3b3fe4c1ac`).
The [CPU report](results/2026-10-03/recognition/autocattlogger-reference-cpu.json)
is `2cf5a0b26fb6b8d9b950616057fb9dd847ac9069943d812111e675ce920796d0`.

Two fixed random 480×640 BGR images and non-square boxes were transformed through
the real author UDP affine and an independent equivalent affine calculation.
Pixels were identical; coordinate round-trip error was at most0.0000611 source
pixels. On the resulting batch2 inputs and horizontal-flip inputs, every captured
backbone branch, heatmap and decoded point/score was bit-exact between author and
timm. Execution took6.35s, CPU FP32, with1.37GB final RSS. No cattle pixels,
training or GPU inference was used. This is a bounded forward/preprocessing
reference proof, not full application parity or pose accuracy.

The isolated `/tmp` dependencies match the checkpoint's MMEngine0.10.4 and
requirements' MMCV2.1.0 (ops-free `mmcv-lite`), with addict2.4.0,
yapf0.40.2 and termcolor2.4.0. Download-cache bytes were under5.8MB, below the100MB
cap; setup and proof completed within15minutes. Installed app Torch2.12.1 was
reused instead of the author's historical Torch1.10.2. No app dependencies were
changed. Namespace-only import scaffolding bypasses unrelated MMPose model
registrations but executes the original backbone/head/UDP source. The unused
Transformers training package is hidden only in this reference process because
its optimizer auto-registration conflicts with current Torch's Adafactor.

An initial import failed at that registration. The first frozen harness then
failed before forward because the author's HRNet override makes chained
`eval()` return `None`. The
[failed frozen source](results/2026-10-03/recognition/autocattlogger-reference-preflight-v1.py),
[protocol](results/2026-10-03/recognition/autocattlogger-reference-preflight-v1-protocol.json)
and [failure](results/2026-10-03/recognition/autocattlogger-reference-preflight-v1.json)
are retained. Calling `eval()` separately corrected the harness; author neural
code, synthetic inputs and decision tolerances did not change.

The isolated setup is reproducible with `uv pip install --no-deps --target` for
the five versions above, using the app Python. The protocol lists every pinned
source file; the namespace loader imports only those author modules. A separate
MPS proof preserves this completed reference; its result follows.

## Synthetic MPS and source-coordinate boundary

The separately frozen [MPS protocol](autocattlogger_mps_protocol.json)
(`1a26647c7f014b351612e3bab003fe22cc4c32d01f3d64cf870c1e756628ad74`)
passed using the same synthetic inputs and weights, actual `mps:0`, FP32, batch2,
without autocast or enabled CPU fallback. All694 bound files still matched after
execution. The [result](results/2026-10-03/recognition/autocattlogger-reference-mps.json)
is `bf63d0a6388bdb28feff41dfedabf763ba66a0bf8d97aab19bb78dcfe00b1854`.

The largest intermediate absolute difference was0.00000501; averaged heatmap
difference was0.000000112 (relative L2,0.00000238). All discrete keypoint peaks
agreed. Largest decoded difference was0.001315 input pixels and0.003159 source
pixels, below the predeclared0.01-input-pixel tolerance. The run took10.96s;
sampled post-forward memory was at most1.46GB RSS and326MB Metal driver memory.
These are sampled memory readings, not an endurance or transient-peak proof.

The exact pinned author's `TopdownPoseEstimator.add_pred_to_datasample` method
was executed without rewriting its body. It maps decoded coordinates using
`point / input_size * input_scale + center - 0.5 * input_scale`.
That differs from inverting the UDP crop affine with `input_size - 1`.
An independent minimal formula matched the author method exactly for both CPU
and MPS decoded points. Thus the earlier affine round trip alone is not claimed
as full heatmap-to-source equivalence. Neural code and the completed CPU proof
remained unchanged. No cattle images or recognition decisions were tested.

## Fixed orientation proposal before cattle outputs

Use the native author inference path first: original image, actual axis-aligned
predicted body box, padding1.25, zero input rotation, 192×256 UDP affine, published
horizontal-flip test and channel mapping. No heading search, PCA rotation or
prediction-dependent choice of view. The saved V5 training pipeline includes
horizontal flips, half-body crops and `RandomBBoxTransform`; the pinned defaults
rotate in[-80°,80°] with probability0.6. This provides some heading augmentation,
but does not establish arbitrary360° or crowded-scene performance.

The author application calls pose on detector boxes before orientation. Its
later anatomical warp uses the predicted withers/tail direction to turn the
coat template upright. Moving that step before pose would be a new method.

A subsequent bounded visual audit should select actual cached body detections at
fixed uniform times in already exposed video, using a deterministic box index
rule before pose outputs exist. Preserve empty selections and all selected
partial, overlapping or ambiguous bodies; do not select ground-truth crops or
open3000+. Record apparent heading, visibility and pose failure descriptively,
without changing this orientation policy. This would be a feasibility check,
not a fresh accuracy test: the V5 training images are not independently audited
and the existing public Purdue/8-calves scenes have already been studied.

Source evidence: [author inference](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/autoCattlogger/autoCattlogger.py),
[post-pose warp](https://github.com/VADL-Purdue/AutoCattlogger/blob/d284cf7fcc2e514bbc4e2f87e50a8dcde7c1f044/autoCattlogger/helpers/helper_for_morph.py),
and [pinned rotation augmentation](https://github.com/open-mmlab/mmpose/blob/759b39c13fea6ba094afc1fa932f51dc1b11cbf9/mmpose/datasets/transforms/common_transforms.py).

## Native-orientation cattle pilot: negative

The [frozen pilot](autocattlogger_pose_pilot_protocol.json)
(`9196cb6546caaca46d95c6d3055e1e6755c3407b208e2a1afb4723cd08f134d5`)
selected16 actual cached body proposals at75/225/375/525seconds. Four spatially
uniform box indices per frame were fixed before pose outputs; no biological
truth or quality ranking entered selection. An
[input-only anatomical prereview](results/2026-10-03/recognition/autocattlogger-pose-preinference-review.json)
recorded headward direction, mixed bodies, obscured anatomy and truncation.
Every selected case was retained. No3000+ frames were read.

Actual MPS FP32 inference produced all160 finite landmarks in6.38s
(8.51s including process setup under the external watchdog). Sampled RSS was
1.19GB and Metal driver allocation326MB. Complete
[raw predictions](results/2026-10-03/recognition/autocattlogger-pose-raw.json),
[execution record](results/2026-10-03/recognition/autocattlogger-pose-execution.json)
and [all16 qualitative reviews](results/2026-10-03/recognition/autocattlogger-pose-review.json)
are preserved. Numerical compatibility did not transfer to reliable anatomy:
landmarks repeatedly fell on neighbors or background, midline points collapsed
near rumps, and truncated bodies remained unresolved. Some outer points were
plausible, but a dependable complete anatomical warp was not established.

This is an AI qualitative diagnostic, not a landmark-accuracy estimate or an
identity result. No confidence threshold, sample exclusion, rotation search or
training was introduced after seeing these failures. The next useful boundary
is one published author image with expected keypoints, to check whether this is
domain failure or a remaining recipe/metadata mismatch. It does not justify
deploying canonical coat matching yet.
