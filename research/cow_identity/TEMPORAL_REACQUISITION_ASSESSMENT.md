# Early temporal pairs for appearance reacquisition

**Decision: a bounded research pilot is justified; automatic enrollment or
production promotion is not. No training or new inference has started.** The
reason to try it is additional temporal variation, not another head or threshold
grid applied to the same 39/60 photographs.

## Evidence available now

The [CPU inventory](results/2026-10-03/recognition/temporal-training-inventory.json)
uses only observations through 629 seconds. The current joint-readout teacher
has 2,804 candidates under the existing photo-quality rule: p10 ≥0.7, no
quarantine, reciprocal detector confirmation, minimum side 64 pixels and no
image-border contact. It does not use embeddings or truth to choose candidates.

| Original confirmed cow slot | Eligible observations | Longest uninterrupted quality run | Runs lasting at least 30 seconds |
|---|---:|---:|---:|
| 1 | 520 | 82 seconds | 7 |
| 2 | 367 | 89 seconds | 3 |
| 3 | 485 | 70 seconds | 3 |
| 4 | 469 | 134 seconds | 4 |
| 5 | 417 | 96 seconds | 5 |
| 6 | 546 | 114 seconds | 7 |

There are 614 frames with at least two eligible known slots. A subsequent
[fixed-pool teacher audit](results/2026-10-03/recognition/temporal-teacher-audit.json)
finds 2,789 inherited names agree with the publisher's matched animal and 15
unmatched rectangles, with no match to a different known or withheld animal.
Nothing is removed or relabeled using this audit. Rectangle matching does not
certify clean single-animal pixels; unmatched geometry does not prove a wrong
biological name. This remains a potentially noisy teacher.

The existing dense MIEW cache has 2,400 foreground descriptors at 330–629,
300 per original slot. Under p10/size/border checks, known slots retain
124–258 each. Their median same-slot cosine at a 30–120-second separation is
0.41–0.61, compared with 0.79–0.86 between adjacent eligible seconds. For cows
3/4/5, median similarity to their nearest same-cow reviewed reference is only
0.367/0.308/0.387. Thus dense temporal data is not merely identical adjacent
photos. It could teach viewpoint continuity missing from the small reference
package. These descriptor differences can also reflect mask errors or
foreshortening; they are not certified novel coat views.

## Cache reuse and provenance limits

The dense cache belongs to the **older publisher-box-initialized Cutie run**.
None of its 2,400 object rows has a complete frame-mask hash equal to the new
joint teacher at the same time. A changed whole mask does not prove every
individual crop differs, but old vectors cannot be silently relabeled as the
new run. Their role here is only to assess representation variation. A new
pilot must derive exact current-teacher foreground crops, reuse any matching
pixel-plus-encoder keys, and encode genuine misses once. No new detector or
propagation run is required.

The old 60-photo farm study trained from ten publisher-prompted early masks per
cow. The later 39-photo package used actual-proposal masks and independent
AI-assisted photo review, but retained only 2/2/5 photos for cows 3/4/5. Neither
trial used thousands of causal temporal positive pairs. The external head used
219 other identities; it tested cross-dataset transfer, not this camera's
temporal invariances. Those negative results still constrain expectations.

## What the paper supports, and what is our hypothesis

[DazzleCow, section 3.2](https://arxiv.org/html/2602.15962v1#S3.SS2), uses
same-timestamp individual masks as contrastive negatives and augmented
instances in a ResNet training procedure. Treating our same-track observations
at different times as positives adds a **teacher-continuity assumption**; it
is not a direct reproduction. Its multiple-day results do not establish that
ten minutes from six calves suffices for open-set reacquisition.

## Minimum credible next experiment

Before encoding or training, freeze one small residual projection of the
original frozen MIEW vectors, an unchanged-vector baseline, one bounded
training budget and one checkpoint. Reuse the existing metric-head code;
changing the backbone, segmentation and matcher together would obscure the
hypothesis. CPU head training should be cheap after the one cached MPS feature
pass. This document is a proposal, not an execution protocol.

1. Split **contiguous early time blocks and entire known identities** before
   forming pairs. A defensible conservative pilot trains on cows 1–4 in
   0–419, leaves an embargo at 420–449, and uses 450–629 plus untrained cows
   5/6 for calibration. Do not then refit on all six after calibration and
   reuse thresholds as though the representation were unchanged. Exact
   grouping and limits must be fixed before any outcome.
2. Form positives only inside an uninterrupted quality-approved track run;
   break at loss, quarantine, ambiguity or missing evidence. Use different
   visible known slots in the same frame as candidate negatives, retaining
   the detector's reciprocal uniqueness and mask separation. Sample time
   intervals rather than letting hundreds of adjacent duplicates dominate.
   Withheld cows 7/8 must enter neither positives, negatives nor a classifier.
3. Review a small fixed uniform sample of the proposed training runs without
   query outcomes. This checks merged bodies, drift and unobserved opposite
   views. Do not turn disagreement into truth-assisted per-frame filtering
   or claim that the early strict matching audit certifies the teacher.
4. Choose the unchanged baseline or the single checkpoint using early-only
   calibration, including withheld-identity rejection. Preserve all rejected
   results. Reset every name and matcher history before later exposed panels
   starting at 930. The recognizer must receive only crop/anonymous temporal
   continuity, never old seeded names, a filename identity, publisher ID or a
   forced six/eight-cluster assignment. Keep all original visible-known,
   unknown and unmatched denominators.

This can test whether learned appearance survives a name reset. If it uses
continuously propagated crops, it is still not proof of physical exit/reentry
or restart recovery. Those require a later source-epoch test with fresh
anonymous localization. All results remain single-camera development evidence;
the detector itself was adapted on some early frames, and there is no new-farm
or independently certified farmer-label claim. Source pixels at 3000 seconds
and later remain closed.

If the fixed teacher-crop sample is contaminated or the one projection does
not improve reset recognition under the existing precision/unknown gates,
stop this branch. More head architectures or fitted thresholds would not
address insufficient trustworthy views.
