# Isolated Cutie runtime package proof

This is a packaging experiment, not an application dependency change. The
original SDK checkout, frozen evaluation files and detector environment remain
unchanged. Nothing was published. No GPU or camera inference was run.

The [patch](cutie_runtime.patch) applies to upstream commit
`ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a`. It changes four constructor calls to
read `model.pretrained_backbone`, defaulting to `true`. Setting it to `false`
avoids downloading ImageNet initialization before loading the complete Cutie
checkpoint. All neural-network definitions remain upstream code.

The isolated wheel uses local version `1.0.0+aidetector.1` and declares only
`torch`, `numpy` and `hydra-core` as runtime requirements. Hydra supplies
OmegaConf and ANTLR. Training and GUI dependencies are deliberately omitted;
this package is for the `CUTIE` / `InferenceCore` inference path, not the SDK's
training scripts or its CUDA-specific convenience downloader. The unmodified
SDK source files, all 13 YAML resources and the original MIT license are kept.

The [saved proof](results/2026-10-03/detection/cutie-runtime-package-proof.json)
records a 171,739-byte wheel and a CPU construction/load time of 0.74 seconds
with application PyTorch 2.12.1. Strict loading succeeds, all 527 checkpoint
tensors are exactly equal, and the model has 35,024,186 parameters. A Python
audit hook rejects network requests throughout the test: initialization with
the flag disabled makes none; omitting the flag attempts the original download
and is deliberately blocked. The test constructs `InferenceCore` and confirms
that einops, Qt, Gradio, thinplate and TensorBoard were not imported.

## Reproduce without changing the application environment

The proof used uv 0.12.5, Hatchling 1.32.4 and the pinned checkpoint already
present in the research cache. Run from the repository root. These commands
create another disposable source copy and install packages into a target
directory, never into `detector/.venv`.

```sh
cutie_proof_dir=$(mktemp -d /tmp/cutie-runtime-proof.XXXXXX)
mkdir "$cutie_proof_dir/source"
git -C /tmp/cow-identity-cutie archive ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a |
  tar -x -C "$cutie_proof_dir/source"
patch -d "$cutie_proof_dir/source" -p1 < research/cow_identity/cutie_runtime.patch
printf 'hatchling==1.32.4\n' > "$cutie_proof_dir/build-constraints.txt"
UV_CACHE_DIR="$cutie_proof_dir/uv-cache" uv build --wheel \
  --build-constraint "$cutie_proof_dir/build-constraints.txt" \
  --out-dir "$cutie_proof_dir/dist" "$cutie_proof_dir/source"
UV_CACHE_DIR="$cutie_proof_dir/uv-cache" uv pip install \
  --python detector/.venv/bin/python --target "$cutie_proof_dir/installed" \
  --no-deps "$cutie_proof_dir/dist/cutie-1.0.0+aidetector.1-py3-none-any.whl" \
  hydra-core==1.3.2 omegaconf==2.3.1 antlr4-python3-runtime==4.9.3
PYTHONPATH="$cutie_proof_dir/installed" detector/.venv/bin/python \
  research/cow_identity/cutie_runtime_proof.py \
  --wheel "$cutie_proof_dir/dist/cutie-1.0.0+aidetector.1-py3-none-any.whl" \
  --installed "$cutie_proof_dir/installed" --upstream /tmp/cow-identity-cutie \
  --checkpoint .cache/cow-cutie/cutie-base-mega.pth \
  --output "$cutie_proof_dir/cpu-proof.json"
```

The existing application environment supplies Torch, NumPy, PyYAML and
packaging; their lock hash and observed versions are retained in the report.
An actual dependency addition still needs the normal pinned application lock,
platform packaging tests and PyInstaller collection of SDK YAML resources.
Constructor/checkpoint equality does not establish output equivalence or
continuous-tracking quality; those remain separate frozen evaluations.

## Object retirement needs a separate SDK correction

The pinned upstream `delete_objects` method is not safe to use unchanged for
continuous anonymous births and departures. A separate CPU probe with real
model inference and synthetic pixels reproduced three lifecycle defects:

- Deleting the first object compacts the object manager but leaves `last_mask`
  unchanged. The next real model step reads the retired object's mask for the
  surviving ID.
- Object summaries remain in `MemoryManager.obj_v` after retirement.
- Removing a bucket containing only permanent memory raises `KeyError` because
  temporary selection/usage tensors do not exist. Deleted bucket offsets also
  remain in `perm_end_pt`.

`cutie_retirement.patch` corrects these specific paths in an isolated SDK copy;
the original source and every previously frozen experiment are unchanged.
`cutie_retirement_proof.py` verifies survivor-channel identity at the next actual
pixel-fusion call, removal of all objects, and insertion/propagation of a new
noncontiguous ID. All eight checks pass in the patched copy; the original has
three failed checks and then the permanent-bucket exception. Five additional
CPU tests exercise 50 repeated add/remove cycles with permanent-only and mixed
memory, and preservation of a different object's bucket.

Reports: `results/2026-10-03/detection/cutie-retirement-original.json` and
`cutie-retirement-fixed.json`. The first probe's undersized synthetic image
failed the SDK's unchanged top-k memory requirement; that preflight is recorded
separately, and both compared runs use the same 96×128 input.

This is SDK state correctness, not an animal-retirement policy or a field
accuracy result. The fixed patch is not yet in the application. An empty camera
should dispose its complete core; upstream historical ID bookkeeping is retained
by design. A measured absence policy must also clear names, review handles and
quarantine state, and must never recreate a biological name from a recycled ID.

A separately frozen [MPS control](cutie_retirement_mps_protocol.json) also passes
all eight ownership checks across 32 independent core lifecycles, using real
FP32 model inference and the same synthetic 96×128 inputs. It disposes each core
and constructs the next one with shared network weights. The
[recorded result](results/2026-10-03/detection/cutie-retirement-mps.json) shows
140,453,120 allocated Metal bytes after every disposal, with no retained object
or historical IDs in the new core. Memory is sampled after disposal and cache
reclamation, not at every transient peak. This verifies the correction on Metal;
it does not test a continuously occupied camera, automatic departure decisions,
full-resolution throughput or biological identity.

## Combined inference package

A separate source copy now combines the runtime, retirement and joint-readout
patches into local wheel `cutie-1.0.0+aidetector.2`. It leaves the original SDK,
the ongoing video experiment and the application's dependencies unchanged.
The three patches apply cleanly to the pinned upstream commit. Building required
fetching the pinned Hatchling build tool once; the subsequent model construction
and inference proof explicitly blocks network access.

The [frozen combined proof](cutie_combined_protocol.json) binds 223 source and
artifact files. The [CPU result](results/2026-10-03/detection/cutie-combined-cpu.json)
verifies exactly four changed SDK Python files, all thirteen original YAML
resources, the original license and only the three inference requirements.
Installed package bytes match the wheel. The real packaged constructor uses
`pretrained_backbone=false`, strictly loads all 527 checkpoint tensors and makes
no network requests; it does not use the research loader's constructor override.

With real FP32 inference on synthetic 96×128 images, all sixteen complete
probability arrays exactly match the separate joint-readout SDK through three
insertion-time buckets and forced long-term memory consolidation. Deleting the
middle bucket, adding a new stable ID, removing all objects and adding another
fresh ID preserves the surviving channels and global own/other-object inputs.
The earlier eight retirement checks also pass. An unprompted empty step bypasses
readout and returns the SDK's all-zero background array; the application should
dispose an empty core rather than treat that array as a calibrated probability.

This complete CPU proof took 2.27 seconds. It establishes compatibility of the
three patches at the actual inference boundary. It does not establish combined
MPS behavior, full-resolution tracking quality, indefinite camera lifetime or
complete installer support. The separate joint-only MPS video evaluation remains
the accuracy experiment.
