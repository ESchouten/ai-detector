# Fixed spatial-tail farm adaptation pilot

The preceding frozen-vector residual head did not solve recognition. A richer
96-image reference bank improved raw correct rank-one retrieval to 793/1,047
matched known observations, but only 13 names survived the unchanged cosine,
margin and three-observation policy. This experiment tests whether adapting the
last spatial layers before pooling can improve that representation. It is not a
threshold search or a claim of automatic biological identity.

The protocol is frozen in `recognition_spatial_tail_protocol.json`. Its 200
predetermined steps use only six initially anchored, imperfect tracking lineages
from seconds 0–419. Negatives are different animals visible in the same frame;
positives are 10–30 seconds apart within an uninterrupted quality-qualified run.
Unknown animals 7/8 never enter optimization. Unlike the preceding four-lineage
head, this is farm adaptation on all six known lineages, not transfer to unseen
known identities.

Only the original MIEWid backbone's final two inverted residual blocks and
`conv_head` may change. Batch normalization statistics and affine parameters,
GeM pooling, the earlier backbone and output normalization remain fixed. There
is one AdamW learning rate, one preservation regularizer and one checkpoint at
step 200. The original 96 reference observations remain identical and are not
reselected using adapted descriptors.

Development work is bounded and cached: 2,582 exact masked crops produce
float32 spatial prefix maps once. The first batch must match full-network
inference, and every cached crop must reproduce its original full-network
descriptor before training. The completed cache and parity report receive a
second immutable binding before optimization. CPU tests verify the actual
network split, allowed gradients and frozen normalization state.

The only comparison is the already exposed 450–629-second calibration panel,
with names reset and the existing .65 similarity, .10 distinct-animal margin and
three-observation policy. All eight publisher animals, missed detections and
unmatched named boxes remain in the denominator. The untouched 96-reference
baseline must replay its prior complete counters and timeline before adapted
scores are accepted. No later query or pixels at 3000 seconds onward are used.

The fixed prediction-only visual review adds seven slot-5/6 examples to the
preceding 16 examples. Slot 5 has no eligible final-bin run; no replacement was
selected. All seven show one substantial body without an obvious merged second
animal, but this limited AI review does not certify every pseudo-label or the
biological identity of each lineage. Real operation without farmer input still
requires separate anonymous-profile and reliable ear-number association work.

The completed pilot is negative. The unchanged bank replayed its entire earlier
baseline exactly. At the fixed operating point:

| Encoder | Correct names / 1,080 known observations | Named errors | Coverage |
| --- | ---: | ---: | ---: |
| Original MIEWid, same 96 references | 13 | 5 unmatched boxes | 1.204% |
| Adapted spatial tail, step 200 | 4 | 0 | 0.370% |

Neither condition named an unknown animal. All cows 3–6 still had no confirmed
names. Raw correct top-one retrieval changed only from 793 to 799 of 1,047
matched known crops, while cosine similarities fell: 44 correct eligible crops
passed the fixed threshold before adaptation versus 18 afterward. The darker,
weakly patterned cow 5 remained a retrieval failure (2 correct top-one crops
before, 1 afterward, out of 178), not merely a threshold rejection. There is no
evidence here to promote the adapted model or start another threshold search.

The MPS prefix pass took 72.95 seconds and peaked at 1.34 GB driver allocation;
maximum descriptor parity error was 1.19e-7. Training 3,972,900 parameters for
200 fixed steps took 12.38 seconds, peaked at 1.61 GB, and changed no state outside
the declared tail. All maps and parity metrics were independently checked finite.
Six focused tests and a separate source/cache audit passed.

The immutable summary is
[`spatial-tail-pilot.json`](results/2026-10-03/recognition/spatial-tail-pilot.json).
The checkpoint stays in the ignored local cache. No production behavior or model
pin changes are made, and no additional tail/head/threshold variants are planned.
