# June 8 localization and torso-crop adaptation

The frozen return-passage control recognized only 2 of 46 visible known-cow
observations. Its cached diagnostic isolates substantial loss before matching:
19 detections, 8 usable crops, 7 correct nearest identities, 4 threshold-passing
known observations, and 2 temporally confirmed names. Only three principal-cow
annotations were both definite and away from the image boundary. These are
camera framing and detection problems as well as recognition problems.

This is a new **research experiment**, not an application change or a successful
identity system. The June 9 result remains recorded, and that day is now an
exposed regression set. The reserved crowded-calf windows remain unopened.

## Frozen first-day inputs

[passage_training_protocol.json](passage_training_protocol.json) binds the
78 native June 8 frames, seven known principal passages, initial detector,
training settings, crop policy and deterministic whole-clip train/validation
split. The two withheld principal cows are excluded. Identifiable withheld
animals in an otherwise included frame cause its exclusion; unidentified
nuisance fragments remain explicitly unknown, so identity-pure localization
training cannot be certified from principal-passage labels alone.

Two independent agents annotate clean native images without model overlays.
These are AI-assisted annotations, not external human-certified ground truth.
Every image, including empty frames, receives an explicit annotation record.
The first-day source manifest binds decoded pixels and original archive/clip
hashes. Separate Purdue COCO photos are not used because their recording-date
provenance is unresolved.

The class labels are:

- **Whole visible cow:** the visible animal extent, clipped to the source image;
  no inferred hidden limbs or body area. This remains the tracking and scoring
  rectangle.
- **Coat torso:** clearly visible coat-bearing trunk from shoulder/chest to
  rump, excluding head, neck, legs and tail. No torso label is invented when
  this region is absent, tiny or unclear.

The fixed split has 53 training frames and 25 validation frames from different
whole passages. A cached official COCO YOLO11s receives 30 epochs of localization
adaptation, using its library's normal validation checkpoint selection. Identity
labels are discarded. This very small, camera-specific dataset does not justify
claims about general farm detection.

## Fixed recognition rule

The detector emits both classes. A torso must be at least 90% contained in
exactly one whole-animal box, and that animal must have exactly one associated
torso. Ambiguity causes abstention. Its evidence receives the whole animal's
track ID. The existing minimum-size, image-boundary and overlap checks apply to
the torso; the displayed whole-animal rectangle can touch the image boundary.

The official MIEW model, 0.65 similarity threshold, 0.10 distinct-cow margin,
three-observation agreement and 5 fps cadence remain fixed. Enrollment uses
only manually reviewed first-day predicted torso crops, at most ten per cow.
Missing enrollment remains a known-cow coverage failure. Names are mapped back
to the whole-animal boxes for the original conservative IoU-based evaluation.
No query identity or annotation enters inference or geometric association.

The training and selected gallery must be frozen before rerunning the existing
June 9 regression. No later threshold or model choice can reuse that run as a
fresh blind test. Results, including a failed adaptation, will be retained.

## Completed first-day preparation

The 30-epoch MPS training completed in 119 seconds. Its selected checkpoint's
validation AP50 was 0.957 for whole animals and 0.937 for torsos. This small
validation set contains only 12 whole-animal and nine torso annotations; these
numbers are localization measurements, not identity accuracy. Training and
validation retained 21 and 13 empty images respectively.

The complete first-day 5 fps pass took 31.48 seconds, producing 117 associated
torso proposals, 36 of which passed the frozen geometry checks. All seven known
cows now have at least one eligible candidate. Independent manual review of
the candidates retained 32 references for six of seven intended cows. Three
exiting rump fragments and the only eligible image of cow 2238 were rejected;
the latter was too blurred to provide reliable coat detail. Cow 2238 remains
an intended-known coverage failure. The 81 geometry failures remain explicit
automatic rejections. A candidate passing the geometry check is therefore not
treated as confirmed enrollment.

The derived [runtime protocol](passage_torso_protocol.json) and
[query freeze](passage_torso_query_freeze.json) bind the selected weights,
32 reference JPEGs and metadata, source reviews, whole-only ByteTrack adapter,
crop association, and unchanged query annotations. The review was AI-assisted;
the inherited protocol's intended farmer confirmation step was not performed
by an external human in this experiment. The installed library's tracker buffer
is measured in processed frames, not native source-video seconds.

[Preparation counts](results/2026-10-03/purdue-torso-preparation.json) distinguish
117 automatically proposed crops, 36 images needing visual review, and 32
accepted references. The 78 images used to adapt the detector are separate
annotation work, not a claim that a farmer should label 78 images during normal
enrollment. The completed later-day torso-control result is described below.

There is also a practical enrollment gap: this research collector retains every
associated 5 fps crop for review. The current application saves the first
eligible image of a track and then waits its default 30-second review interval.
A short walking passage would therefore usually expose fewer photos in the
real Herd screen. This experiment uses actual predicted crops and the real
gallery format, but it does **not** reproduce the application's photo-retention
cadence. The 32-reference result must be described as richer research
enrollment, not a validated one-pass farmer workflow. A bounded burst of a few
photos is a possible later application improvement; it is not part of this
frozen control.

The final independent audit passed all 99 frozen file hashes, reference
selection, unchanged query truth, whole-box mapping and eight focused tests.
The approved query freeze SHA-256 is
`a622753ee8b97c0551532b6a0a01ba937967578606d802aee2641e73ebbfe351`.
The frozen MPS query completed all 508 processing frames in 19.21 seconds.
No model, gallery, threshold or annotation changed after that freeze.

The unchanged scorer invocation is:

```sh
PYTHONPATH=detector/src MPLCONFIGDIR=.cache/matplotlib detector/.venv/bin/python \
  research/cow_identity/passage_metrics.py \
  --predictions .cache/cow-passage-query-torso/predictions.json \
  --annotations research/cow_identity/results/2026-10-03/purdue-passage-annotations.json \
  --protocol research/cow_identity/passage_torso_protocol.json \
  --manifest research/cow_identity/results/2026-10-03/purdue-passage-manifest.json \
  --output research/cow_identity/results/2026-10-03/purdue-torso-production.json
```


## Completed later-day regression and causal diagnosis

The adapted localizer matches **51 of 76** annotated visible animals, compared
with 19 for the original detector. All 49 definite annotations are matched;
the remaining misses are uncertain edge fragments. Identity coverage still
fails: **3 of 46 visible known observations are named correctly (6.52%)**,
with zero wrong or unmatched names. Only three of seven known passages receive
any name. Zero observed errors from three correlated correct names does not
establish reliable precision. The unchanged definite-only sensitivity is
3 of 40 known observations (7.5%). No withheld principal is named (0/10), and
no unresolved nuisance fragment is named (0/20).

[The full outcome](results/2026-10-03/purdue-torso-production.json) retains
original whole-animal coordinates and truth, including missed and rejected
observations. This is an exposed regression, not a second blind test, and the
adaptation is not promoted to the application.

[The cache-only causal diagnostic](results/2026-10-03/purdue-torso-diagnostics.json)
replays the actual `GalleryIdentifier` on all 508 frames, using only read-only
stored embeddings. Every replayed name agrees with the frozen output. A missing
cache vector or differing output aborts; no encoder inference or threshold
fitting occurs. The known-cow loss stages are:

| Stage | Known observations remaining |
| --- | ---: |
| All annotated visible known cows | 46 |
| Matched whole-animal prediction | 41 |
| Unique associated torso | 23 |
| Torso passes existing geometry checks | 10 |
| Correct nearest gallery identity | 10 |
| Correct single-sample match at .65 similarity/.10 margin | 7 |
| Three-observation actual confirmation | 3 |

All 13 rejected associated known torsos touch the image boundary; size and
crop overlap remove none of these scored examples. Another 18 matched whole
animals lack a unique detected torso. The usable known crops all have the
correct nearest identity. Two fail only absolute similarity, one fails both
similarity and margin. Removing thresholds entirely would also incorrectly name
one withheld principal, so this does not justify a blanket threshold reduction.

Three single-sample matches occur at the beginning of otherwise successful
confirmation sequences; the three correct names appear 0.4 seconds later.
Cow 6079 crosses the threshold for only one sample before its confidence falls.
Four temporal sequences end when a torso touches the boundary, including all
three confirmed sequences; one pending sequence ends on a threshold failure.
No simultaneous duplicate-name conflict occurs. Localization has improved,
but brief availability of eligible coat evidence still dominates this camera.

| Cow | Visible | Whole match | Associated torso | Eligible | Single-sample correct | Confirmed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2234 | 7 | 6 | 4 | 2 | 0 | 0 |
| 2238 | 6 | 5 | 3 | 0 | 0 | 0 |
| 5676 | 9 | 9 | 5 | 2 | 2 | 1 |
| 5953 | 7 | 6 | 3 | 1 | 0 | 0 |
| 6079 | 6 | 5 | 3 | 1 | 1 | 0 |
| 6102 | 6 | 5 | 2 | 2 | 2 | 1 |
| 6110 | 5 | 5 | 3 | 2 | 2 | 1 |

## Photo collection replay

A separate [first-day retention replay](results/2026-10-03/purdue-torso-retention.json)
uses the actual empty-gallery collector at this experiment's 5 fps/.2-second
cadence. Its normal first-photo/30-second policy offers 10 photos, nine of which
passed the existing independent review. A research-only bounded first-three
photos per track followed by the normal interval offers 20 photos, with 19
review-accepted examples. Both still cover six of seven intended cows; the
blurred 2238 passage remains unresolved. The application's default 1 fps
preset is a separate cadence and is not claimed to be reproduced here.

This establishes that a short collection burst can supply more useful views,
not that those smaller galleries improve recognition. The frozen query used
its original richer 32-reference gallery throughout. Neither this retention
variant nor the torso detector changes production behavior.

## Frozen boundary and short-continuity follow-up

The next two research arms are fixed in
[passage_torso_followup_protocol.json](passage_torso_followup_protocol.json),
with 108 bound file hashes. They reuse the exact first-day gallery, saved raw
whole/torso predictions and track IDs, source pixels, original annotation set,
encoder and matching thresholds. No detector inference or retraining is needed.
The first arm removes only the torso image-boundary rejection; its wrapper
preserves the original crop pixels exactly. The second adds at most one second
of a previously confirmed name on a continuously visible whole-animal track
when **no torso rectangle intersects it**. Partial or ambiguous torso evidence
clears the hold, as do present but unconfirmed evidence, competing pending or
confirmed names, lost/duplicated/reused track IDs, time reversal and gaps.
A held name does not renew its expiry. Each clip starts with fresh state.

These are hypotheses derived from the exposed regression's failure analysis,
not production changes or new blind evaluations. New border-crop features will
be cached separately; the original query cache and failed results are preserved.
Both controls are complete; the results are below. Nineteen focused
passage/continuity tests pass, including exact crop-pixel preservation and
pending-name conflicts.

The follow-up audit passed independently after a pre-run JSON arm-order bug
was corrected and regression-tested. No outcomes were generated with that bug.
The final follow-up freeze SHA-256 is
`adbee3bd535b82698f32383851155bd89ddb79a1a5f44f6e4c8398c1dcfb4f7a`.
A continuously switched tracker ID cannot be independently detected by the
short-hold rule; observed loss/reuse does reset it.


### Completed boundary/continuity controls

The fixed border-only arm names 5 of 46 known observations (10.87%), with no
incorrect observed names. The one-second absence-only continuity arm produces
identical names on every one of the 508 processing frames. It therefore adds
no measured coverage. The new cache contains 90 additional border-crop vectors;
processing took 9.60 seconds excluding encoder startup. Both arms fail the goal
and remain research-only. See the [summary](results/2026-10-03/purdue-torso-followup-summary.json)
and [border diagnostic](results/2026-10-03/purdue-torso-border-diagnostics.json).

Allowing the border produces 23 usable matched-known torsos, 16 correct nearest
identities, eight threshold-passing correct observations and five confirmed
names. Unthresholded nearest-neighbor assignment would also produce seven wrong
known names (three belong to cow 2238 with no references) and five false names
on withheld principals. No threshold reduction is justified by this result.
The small correct-name count cannot certify the zero-error point estimate.

The [crop/reference audit](results/2026-10-03/purdue-torso-crop-audit.json) uses
read-only cached vectors. Its 28 comparison rows reveal strong viewpoint and
partial-crop mismatch. The 32 selected references cover only 0.6–1.2 seconds
per cow, mostly adjacent central views. Cow 2234's nearest true similarities
across four scored torsos are .421/.552/.517/.412; a diagonal entering crop
prefers another cow. Cow 6079 has .654 similarity and .189 margin at its central
view, but entering/exiting partials score .342/.363 and prefer other cows.
These observations motivate a separate first-day-only view-coverage experiment,
not query-based gallery selection. Whole localization alone is no longer the
main bottleneck. Even perfect instantaneous matching of all 23 available
known torsos would cover only half of the 46 visible known observations.

## First-day view coverage and longer confirmation continuity

The next enrollment control fixes ten chronological review candidates per known
first-day passage, including entry and exit, without using embeddings or query
scores to choose them. Its [selection protocol](passage_view_enrollment_protocol.json)
binds all 70 candidates. Two independent AI reviewers accept 55 references and
reject 15; there is no backfilling. These are 9/4/9/9/8/8/8 photos for cows
2234/2238/5676/5953/6079/6102/6110. Four softer but usable entering torso images
of 2238 pass a second independent review; its severely smeared later images
remain rejected. One candidate from 5676's clip is correctly rejected as the
following animal. All seven intended cows now have references, without claiming
that a dark, weakly patterned reference guarantees distinguishable identity.

[The new query freeze](passage_views_query_protocol.json) separates three fixed
conditions: original gallery plus a five-second hold, chronological gallery
with border evidence, and chronological gallery plus that hold. The hold keeps
only a genuinely confirmed identity through weak evidence; it does not lower
matching thresholds. An independent 0.6-second observation-gap limit, a
non-overlapping whole-box jump, track loss/observed reuse, time reversal or
strong contrary pending identity clears continuity. Unsafe continuity resets
actual matcher agreement before matching, and competing pending identities
also suppress held names. A held name never renews its five-second expiry.

The original failures remain intact. These conditions are frozen before their
query runs and have 23 focused tests. Final independent input/implementation
review and the shared GPU slot are pending. The outcome must include all seven
known cows and both unknown principals, with the same original truth.
