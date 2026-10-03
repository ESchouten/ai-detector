# Exact reciprocal detector bounds: rejected

The [single frozen CPU control](detection_reciprocal_geometry_protocol.json)
kept every original slot, order, label, name and temporal decision. It replaced
only a slot's coordinates and confidence with its existing unique reciprocal
same-frame detector proposal. Unpaired slots remained; unpaired proposals were
never added. Both named and unnamed paired slots used the same rule. This is
distinct from the earlier all-raw, union, mean and padding controls.

Five synthetic boundary tests and an independent source/hash review passed
before scoring. Every original panel result was reproduced exactly before the
changed condition was scored. The [complete result](results/2026-10-03/detection/cutie-reciprocal-geometry.json)
retains all eight calves, unmatched outputs and unknowns.

| Exposed panel | Original correct names | Changed correct names | Changed coverage | Changed precision | Wrong known / unknown named / unmatched named |
|---|---:|---:|---:|---:|---:|
| 330–629 | 1,287 | 1,265 | 70.28% | 97.46% | 2 / 0 / 31 |
| 930–1229 | 1,346 | 1,330 | 74.09% | 98.15% | 1 / 1 / 23 |
| 1230–1529 | 1,413 | 1,405 | 78.10% | 98.74% | 0 / 0 / 18 |
| 1800–2099 | 1,135 | 1,098 | 61.03% | 96.32% | 0 / 0 / 42 |
| 2700–2999 | 1,331 | 1,311 | 73.61% | 96.40% | 9 / 0 / 40 |

All five changed panels fail the original 99% precision requirement. Counts of
output boxes and emitted names are identical within every comparison; only
their geometric association changes. Removing the previous control's extra
raw proposals therefore does not make detector coordinates a safe substitute.
The original late-panel failure remains, and no further output-geometry sweep
is justified by this result. [Publisher annotation uncertainty](ANNOTATION_TEMPORAL_GEOMETRY.md)
does not rescue either score or prove biological identity correctness.

This replay uses previously exposed data, not a new blind test, and performs no
model inference. A development-speed lesson: the frozen validator decoded all
5,999 stored masks again even though this transform consumes only already
validated immutable prediction JSON. Future CPU-only output controls should
bind that JSON, its completed full-validation report and baseline counter
parity; repeating mask decoding is unnecessary when no mask-dependent input
changes. This completed experiment was not interrupted or relaxed.
