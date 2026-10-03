# Optional Cutie runtime

This directory contains the unchanged, audited `cutie==1.0.0+aidetector.2`
inference wheel. It is based on [upstream Cutie](https://github.com/hkchengrex/Cutie)
revision `ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a`, under the included MIT
license. [provenance.json](provenance.json) records exact artifact and patch hashes.
No checkpoint, training data or generated inference cache is included.

The three patches add an opt-out for unused ImageNet initialization, correct
object-memory retirement, and perform the shared object readout across insertion
buckets. The latter is an experimental algorithm change, not an upstream bug fix.
The package keeps all original model configuration resources and limits its
dependencies to Torch, NumPy and Hydra. Training and GUI tools are unsupported.
The application's adapter strictly loads the separate, hash-pinned full Cutie
checkpoint and never asks the SDK to download backbone weights.

Install from a checkout or an extracted AI Detector source archive, from
`detector/`:

```sh
uv sync --locked --no-dev --extra default --extra identity-continuous
```

The SDK is also a development dependency so the normal type checks can resolve
its adapter types. Ordinary runtime installs, NVIDIA bootstrap exports and
container installs do not select the optional extra. Installing it does not wire
continuous tracking into the application or change the current detector behavior.

Plain pip does not read `tool.uv.sources`, and this custom version is not on PyPI.
From a checkout or extracted source archive, supply the wheel directory explicitly:

```sh
python -m pip install --find-links vendor/cutie '.[identity-continuous]'
```

The AI Detector wheel itself does not embed this wheel. A wheel-only installation
needs a separately supplied matching Cutie wheel (or a matching `--find-links`
location); `pip install 'aidetector[identity-continuous]'` alone cannot fetch it.
Plain installation without this extra remains unaffected.

## Rebuild and audit

Export the pinned upstream revision into a clean source directory. Apply
`cutie_runtime.patch`, `cutie_joint_readout.patch`, then `cutie_retirement.patch`
with `patch -p1`. Change only the project version from `1.0.0+aidetector.1` to
`1.0.0+aidetector.2`, remove any `.orig` patch backup files, then build with
`uv build --wheel` and a build constraint
`hatchling==1.32.4`. Compare the resulting SHA-256 with `provenance.json` before
replacing the artifact. Dependencies are resolved by the application's `uv.lock`.

The repository's `research/cow_identity/CUTIE_PACKAGING.md` links the frozen
offline CPU and Metal proofs. They verify strict loading of all 527 checkpoint
tensors, model resources, object retirement/reinsertion and probability parity
with the measured patched SDK. They do not establish farm accuracy or installer
support for this still-unwired experimental adapter.
