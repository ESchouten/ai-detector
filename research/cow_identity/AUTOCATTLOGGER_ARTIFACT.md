# Published pose artifact: safe loading and topology

The bounded follow-up downloaded only the author-published HRNet checkpoint:
768,697,571 bytes in 40.5 seconds. The normal public Box URL works without the
`.pth` suffix in the README. SHA256 is
`a23cfd37a78a0745392e5b0457dd468e9afbea3eebbbf19b94d32b988734438f`;
its SHA1 matches the public file metadata. Provenance, every tensor shape and
source hashes are in
[`autocattlogger-checkpoint.json`](results/2026-10-03/recognition/autocattlogger-checkpoint.json).
No MaskRCNN, dataset or framework environment was downloaded. No forward pass,
training or GPU work occurred.

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

## Proposed next proof — no execution authorized by this document

Use the author's pinned MMPose HRNet, residual blocks and heatmap head as the CPU
reference, using the actual saved V5 configuration. Compare those with the
minimal timm backbone/head on fixed synthetic192×256 inputs and their horizontal
flips. Require strict state loading, record intermediate branch and raw heatmap
differences, preserve all ten channels, then compare flipped-channel averaging
and UDP coordinate decoding. Also verify a synthetic non-square source crop's
bbox-center/scale/affine round trip; equal network outputs alone would not catch
a coordinate or left/right swap error.

The current app has no MMCV/MMEngine/MMPose installation. The strongest small
reference route needs a separately approved, isolated CPU dependency target for
MMEngine and MMCV-lite, then a deliberately narrow import of the pinned author
modules without loading MMPose's unrelated EDPose/compiled-ops registry. No
neural forward code should be rewritten or replaced with timm in that reference.
If this cannot be isolated simply, stop that route and retain equivalence as
unverified. The official PyTorch-only HRNet source can give a useful independent
architecture cross-check, but must not be mislabeled as the exact author SDK.

Freeze exact source/dependency/input hashes before any reference forward. A
passing CPU reference comparison would precede, not replace, a separate bounded
MPS comparison. Neither proof would establish pose or cross-visit recognition
quality; those need a later frozen visual experiment with missed and unknown
animals retained. The saved V5 file and previously exposed Purdue videos cannot
create a new blind accuracy test.
