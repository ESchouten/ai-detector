# Early temporal projection pilot

This is a bounded research attempt at appearance matching after naming state is
reset. It does not assume that continuous tracking already solves identity across
visits, and it does not change application behavior.

The completed joint-readout teacher supplies the actual foreground masks at one
frame per second from 0–629 seconds. The descriptor pass keeps every predicted
slot, including unknown, weak and missing-name observations: 5,011 crops. It also
encodes the same 27 independently AI-reviewed reference photographs dated no later
than 419 seconds. Reference counts for cows 1–6 are 6/6/1/2/5/7. Later reference
photographs are excluded, and unknown cows 7/8 have no reference.

Training uses only slots corresponding to the four initially confirmed cows
1–4 during 0–419 seconds. A fixed quality rule requires a reciprocal detector
match, no quarantine, mask probability p10 ≥0.7 and an unclipped crop at least
64 pixels on each side. The 369 anchor frames supply 1,088 positive pairs. Each
positive comes from the same uninterrupted quality run, 10–30 seconds away,
closest to 20 seconds. Negatives are other qualified cows visible in that exact
anchor frame. Unknown cows 7/8 and untrained known cows 5/6 never enter the loss,
including as negatives. The 420–449-second interval is an embargo.

A deterministic 16-crop contamination sheet was saved before visual review:
one midpoint of the longest eligible run in each 105-second bin for each training
cow. The parent agent inspected all crop/context pairs and found substantial
single-cow foreground without obvious merges or background-only masks. No sample
was removed. This does not certify biological identity across the entire teacher
pool; the pseudo-label assumption remains explicit.

The pinned official MIEWid encoder stays frozen. The CPU model is a small
same-dimensional residual projection, 2152→256→2152, with a zero-initialized output
layer, 0.1 residual scale and L2 normalization. Its initial output equals the base
descriptor. One fixed 20-epoch checkpoint uses only same-frame contrastive
negatives plus a cosine-drift penalty. There is no backbone adaptation, epoch
search, threshold search or retraining on the other two known animals.

The unchanged baseline and the single candidate use identical observations and
gallery photographs. Naming starts empty at 450 seconds. Calibration ends at
629 seconds, using the existing similarity 0.65, distinct-animal margin 0.10 and
three-observation agreement. All eight visible animals and unmatched named boxes
remain in the strict scoring denominator. Cows 5/6 are reported separately as
untrained known animals. Only a candidate meeting 99% precision, at most 1%
unknown false naming and higher correct coverage than baseline can be selected.
Selection is not evidence that the overall 60% coverage target or field-use goal
has been met. Any later-panel comparison requires a separate freeze; pixels at
3000 seconds and later remain closed.

The first extraction attempt failed before encoding because its input guard
expected uint8 masks, whereas the immutable birth runner saved uint16 PNGs.
The original freeze, source and failure report are preserved. Version 2 accepts
either lossless integer representation, verifies every mask/source hash and
rejects IDs outside the actual frame's recorded object inventory. The independent
preflight and uint16 regression passed; no algorithm, sample or training choice
changed.

## Completed result

The descriptor pass completed 5,038 rows in 120.2 seconds on MPS with a 1.31 GB
driver peak. Six exact crop-cache hits avoided re-encoding. The fixed residual
pilot completed in 2.83 seconds on two CPU threads. Before scoring, one additional
untrained comparison was frozen: 16 quality-qualified early lineage photographs
per known cow, chosen by the existing medoid-first/farthest-first rule. This
96-reference bank changes reference coverage, not the model. It is not a claim
of 96 separate farmer confirmations.

All conditions retain 1,080 visible-known and 360 visible-unknown observations
over the same 180 calibration frames. The residual candidate was rejected.

| Fixed condition | Correct names | Unmatched named boxes | Known coverage | Conservative precision |
|---|---:|---:|---:|---:|
| Original encoder, 27 reviewed references | 34 | 0 | 3.15% | 100% |
| Residual epoch20, same 27 references | 55 | 5 | 5.09% | 91.67% |
| Original encoder, 96 lineage references | 13 | 5 | 1.20% | 72.22% |

There were no matched wrong-known or unknown names in any condition. Unmatched
names remain errors; they have not been reclassified as harmless geometry noise.
None of cows 3–6 obtained a confirmed name. No later query was run and no
threshold, epoch or gallery choice was changed after these results.

Retrieval and acceptance fail for different reasons. Among 1,047 matched-known
observations, raw top-one identity is correct for 501 original, 578 residual and
793 dense-bank observations. The dense bank therefore helps retrieval materially
despite failing the naming policy: cow3 improves from 62/174 to 174/174 correct
rankings, and cow4 from 4/178 to 149/178. Cow5 remains 2/178; this is incorrect
retrieval, not merely conservative thresholds.

For the dense bank, 747 correctly ranked observations pass crop geometry, but
only 44 pass the frozen similarity threshold. All 44 also pass the margin;
three-observation agreement ultimately leaves 13 correct names. Median similarity
among correctly ranked dense-bank observations is approximately 0.536 for cow3,
0.507 for cow4 and 0.560 for cow6, below the fixed 0.65 threshold. Cow5's two
correct rankings have nearly zero distinct-animal margin. These distributions
are diagnostics, not grounds for post-hoc threshold selection.

Reproducible reports are
[`temporal-projection-pilot.json`](results/2026-10-03/recognition/temporal-projection-pilot.json)
and
[`temporal-retrieval-distributions.json`](results/2026-10-03/recognition/temporal-retrieval-distributions.json).
The latter records per-cow correct/wrong similarity and margin quantiles.

## Follow-up: spatial-tail adaptation

The proposal below was subsequently executed under its own frozen protocol.
It did not improve recognition: correct naming coverage fell from 1.204% to
0.370% at the unchanged operating point. See the completed
[spatial-tail pilot](SPATIAL_TAIL_PILOT.md) for its exact recipe, numerical checks
and retained negative result. The following text records the original rationale;
it is not an outstanding training request.

A bounded spatial-tail adaptation is more informative than another global-vector
head. The actual MIEWid EfficientNet contains 24 blocks in its final stage. Train
only its last two InvertedResidual blocks and the following convolutional head:
approximately 4 million parameters, rather than the whole 53-million-parameter
backbone. Keep all normalization statistics/affine parameters and GeM frozen.
Cache the unchanged prefix feature maps once, after verifying exact prefix+tail
versus full-model output parity, then train a single fixed 200-step checkpoint on
those spatial maps. This allows changing local feature extraction before pooling;
the failed residual head could only transform an already pooled vector.

Using all six initially confirmed animals at 0–419 seconds is scientifically
reasonable for explicitly farm-specific adaptation. It is a different question
from transfer to unseen identities, so cows5/6 would no longer be described as
untrained. Unknown7/8 must still be absent from every optimization input. The
same uninterrupted-run positives, simultaneous negatives, noisy-teacher caveat
and 30-second embargo remain. Use the already selected 96 reference observations
unchanged for both baseline and adapted model, with no later gallery selection.

The proposed budget was one short MPS prefix pass and 200 small-tail steps,
estimated at a few minutes with the existing 8 GiB cap. Its separate protocol,
source review and execution are recorded in the follow-up report. The evidence
does not show that cow5's missing views can be recovered or that appearance
matching generalizes across visits or farms.
