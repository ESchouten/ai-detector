# Bounded YOLO training arithmetic check

Before the proposed tag/head/body localization pilot, one frozen synthetic batch
was evaluated with native Ultralytics YOLO11s training forward, task-aligned loss
and backward on CPU and MPS. No optimizer was constructed and no weights were
updated. This is a numerical diagnostic, not an accuracy experiment or a general
certification of MPS training.

The [protocol](yolo_training_numerics_protocol.json) binds 231 files: the official
cached COCO checkpoint, every installed Ultralytics Python source, default loss
configuration, diagnostic/test source, actual initialized three-class state, and
batch tensors. The full resulting state and input hashes were verified again on
each device immediately before its pass. Seed17, FP32, two random1280×1280 images,
six positive boxes across three classes, native training batch normalization and
no dropout/augmentation were fixed before execution. The random input avoids
uniform-image ties. No research photographs or evaluation labels were used.

The [complete report](results/2026-10-03/ear-tags/yolo-training-numerics.json)
retains all native output, feature, gradient, assignment and buffer comparisons.
Full tensor captures remain in `.cache/cow-yolo-training-numerics/{cpu,mps}.pt`.
CPU and MPS took4.01 and3.26 seconds respectively for their forward/backward;
the whole subprocess finished in10.88 seconds, within the180-second limit.
Peak process RSS was3.20GiB and Metal allocation4.37GiB, below the8GiB bounds.

| Comparison | Observed difference |
|---|---:|
| Maximum output/feature relative L2 | 0.00002655 |
| Loss-component relative L2 | 0.000002246 |
| Combined gradient relative L2, CPU FP64 norm calculation | 0.004238 (0.424%) |
| Largest gradient relative L2 excluding the four near-zero BN-bias tensors | 0.007002 (0.700%) |
| Foreground mask, target boxes, labels and target indices | Exactly equal |
| Soft assignment-score relative L2 | 0.00002380 |

All255 computed parameter gradients were finite. The same one fixed DFL parameter
had no gradient on both devices. No CPU-zero/MPS-nonzero gradient appeared. The
raw maximum per-parameter relative error was1.339: its CPU gradient norm was only
0.000002936 and absolute L2 difference0.000003932. All four ratios above1% were
near-zero batch-normalization bias gradients. These are retained in the full
report; the table's exclusion is a descriptive breakdown, not an acceptance gate.
The aggregate gradient calculation includes every computed gradient.

This batch does not reproduce the gross TrOCR projection-backward discrepancy,
but the gradients are not bit-identical and differ by about0.4% globally. No
post-hoc numerical pass threshold was chosen. Tiny forward differences can
change discrete task-aligned assignment or other internal choices; gradient
disagreement alone does not establish an arithmetic defect. The recorded target
indices were identical here, while soft target scores differed slightly.
Results do not validate an optimizer, a whole training run, other resolutions,
other Torch versions or actual ear-tag localization. Any training pilot still
needs its separate frozen data, recipe and honest evaluation.
