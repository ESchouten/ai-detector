# A real entry and exit sequence

This records the source inventory and the subsequently executed **one-slot,
no-additions lifecycle control**, which failed: the original name transferred
to the entering animal. The 22-frame
selection was fixed before rendering, in `passage_entry_selection.json` (SHA256
`5ba8ee4e89327698c98eae347c8c0847b475ac3ecc23f972dcccd610e2115c40`).
No model, GPU, reserved calf frames, new dataset, or threshold search was used
to choose the inventory. The later frozen model experiment is described below.

## Selected source

Two already exposed June 8 Purdue clips come from the same original recording,
`cam24_2022-06-08_08-29-23`:

| Principal from publisher CSV | Native interval, exclusive end | Video SHA256 |
| --- | --- | --- |
| 5676 | 79542–80049 | `723ec0dcb96e7c789f47bd088a6283b829e630216dd490fd507d3d5674b5629e` |
| 5953 | 80052–80292 | `a31dfef670eff62f2394d4b70964ef05d9f100b553066552d1b2a5782094ae4b` |

The selection is `range(79962, 80278, 15)`: 22 native frames at exactly 2 fps,
covering 0–10.5 seconds. Source resolution is 1920×1080 at 30 fps. The first
frame is local frame 420 of the 5676 clip; the second clip begins at sequence
time 3 seconds. Native frames 80049–80051 are unavailable, but none belongs to
the processing lattice. There is no interpolated, repeated, or missing selected
frame. This is not a reconstruction of the entire native-rate recording.

The source archive is `datasets/AutoCattlogger/sampleVideos1.tar`, SHA256
`0fcf0c7ee97d92d24dffdf2366c07adfc5e300befa68a73d84e890e7709507d4`.
Exact member names, selected local/global indexes and current AVI hashes are
bound in the selection. Its nested `pixels_exposure` strings were inherited
from the original pre-exposure inventory; **both clips are now already exposed**.

## Visible lifecycle

The clean contact sheets show 5676 clearly alone initially. A different cow
enters from the lower left around 1.5 seconds while 5676 leaves on the right.
Both are briefly visible across the file boundary. The entrant walks through
the scene and disappears; the final frames show an empty passage.

For a future control, seed only the initial visible animal as 5676. Treat the
entrant as **nameless in this session**, although the next publisher clip labels
it 5953 and earlier appearance experiments used that biological identity.
There must be no inherited appearance-gallery identification in this control.
The old annotations contain `cow: null` for some entering/exiting fragments.
They remain unchanged: cross-clip continuity needs a separate reviewed
lifecycle annotation, not an implicit rewrite of the old truth.

`passage_entry_inventory.py` verifies the selected sources and renders native
PNGs plus two clean sheets under `.cache/cow-passage-entry-inventory/`. All 11
selected frames that overlap the old 1 fps annotation inventory have exactly
the same decoded pixel hashes. Rendered manifest SHA256:
`f6c9fe1ceebb7938defde151b07ae5926ab6ee660ff4dc783547f4fa4154da4f`.

## Annotation review completed before inference

The separate lifecycle annotation is
`results/2026-10-03/purdue-entry-annotations.json`, SHA256
`e087ea0891e49ac63f9cfdb2cce21df0c5363ce1fa654c877ecfea31f085d191`.
All 22 frames are present: nine observations of the initial known animal,
14 of the initially nameless entrant, and five empty frames. The entrant's
last possible trailing fragment at 8 seconds remains explicitly uncertain;
8.5–10.5 seconds are empty. Old native-frame extents were retained exactly,
and new half-second extents were drawn from clean native frames. Cross-clip
identity links exist only in this new annotation; historical single-clip
annotations remain unchanged.

The cattle research agent independently reviewed clean continuity, complete
overlays and selected native frames. It found no omitted third animal or
inconsistent clip boundary. Review provenance is recorded in the annotation
and `purdue-entry-clean-review-cattle.json`. The parent also reviewed both
clean sheets independently. These are AI-assisted reviews, not external
human-certified ground truth. This review preceded identity inference.

## Minimal useful future experiment

1. Bind the completed separate 22-frame lifecycle annotation and exact source
   hashes into the eventual experiment freeze, preserving uncertain edge
   fragments and empty frames.
2. Initialize a single reviewed mask and name only on the first frame. Run a
   control with no entrant insertion: measure whether the known name jumps to
   the entrant or survives in the empty scene.
3. If justified, freeze a separate addition arm. Only current raw detector/SAM
   evidence may propose the entrant; no annotation, biological ID, or future
   frame may be passed into inference. The new stable object starts nameless.
   Invoke Cutie once per timestamp, even on an insertion frame.
4. Score the initial cow's continuity, any wrong name on the entrant, entrant
   proposal latency/duplicates, and leftover masks after exits. Preserve all
   22 timestamps and the initially nameless animal's denominator. Document
   source epoch and object-generation resets separately from biological names.

The existing stable-ID/channel-compaction CPU checks are a prerequisite, not a
dynamic-lifecycle result. Deletion must not transfer a retired name to a newly
inserted object. No insertion rule or runtime behavior has been implemented or
calibrated using this inventory.

## Executed no-additions control

The first control is frozen in `passage_entry_protocol.json`, SHA256
`c936a108e9ba17674c29d42fa5de5292772acb42621850ac72e762705fa0c16e`.
Its 50 bound files include every native image, annotation, exact first-frame
actual detector proposal, model checkpoints, production resize helper and reused
decision/scoring helpers. All hashes and the app interpreter's library versions
passed CPU preflight. Three focused CPU tests verify cadence, fresh half-second
corroboration, unknown-name errors, and empty-frame errors.

The unchanged cached proposal is `[50, 114, 1155, 720]` at 1280×720 with actual
confidence 0.72022557. Two AI reviewers accepted it as one clear principal cow,
not a mixed-subject box. It is not the annotation rectangle. The precise resized
native image matches the prior detector pixels. A single CPU SAM invocation
produced the first-frame mask in 0.629 seconds. Its SHA256 is
`168e81feadab31e8081d032a00e44bafe2e40b6941b32c297b14ff2717dd33f0`.
The parent independently inspected and accepted that mask before any propagation.

`passage_entry_control.py` reuses the selected Cutie initialization, original-mask
probability summaries, LCC geometry, reciprocal pairing and naming decisions.
Only slot 1 exists, named 5676. Fresh raw whole-cow detector proposals and naming
decisions run at every half second; quarantine keeps its original 1 Hz history.
With only one slot, no donor/receiver pair can form. The adapted Purdue detector
preserves its previously frozen FP32 MPS contract; this is not a claim that the
hardware universally requires FP32. There is no automatic entrant insertion,
deletion, replacement seed, later correction, or appearance lookup.

The post-review execution freeze is `passage_entry_execution.json`, SHA256
`7f750f40392efa57a9bf816e4044c526760069cf2f04b1bc65e2e4877be5fa1c`.
All 22 frames completed in 6.295 seconds using the app's Torch 2.12.1 interpreter,
Cutie FP32 on MPS and the fixed FP32 MPS detector. Peak measured MPS driver
allocation was 1,992,589,312 bytes. The complete output is
`.cache/cow-passage-entry-control/predictions.json`; strict scoring is preserved
in `results/2026-10-03/purdue-entry-baseline.json`.

The original animal was correctly named in 7 of 9 visible observations
(77.78% coverage), but its name was inherited by the entrant in 4 of 14 unknown
observations (28.57% unknown false acceptance). Conservative named precision
was 7/11, or 63.64%. All four wrong names occurred at 5.5–7.0 seconds. There
were no named unmatched boxes or names on empty background. The propagated
mask disappeared after the uncertain trailing fragment at 8.0 seconds; all
five empty frames had no mask. These results preserve partial animals and the
uncertain fragment in the original denominator; they are not a passing result.

Strict input validation and scoring completed before the production continuity
patch was allowed to change a bound domain file. Historical freezes remain
unchanged; replay must use the originally bound source revision.

## Why the name transferred

The CPU-only ledger `results/2026-10-03/purdue-entry-forensics.json` binds all 22
original images, propagated masks, current proposals and name states. Complete
side-by-side sheets are under `.cache/cow-passage-entry-control/forensics/`.
Truth overlap is used only by this posthoc diagnostic, never by inference.

| Time | Observed original-slot state | Name |
| --- | --- | --- |
| 3.0 s | Correct old cow; p10 0.800, reciprocal proposal IoU 0.884 | 5676 |
| 3.5 s | Still old cow, but mask shrinks; p10 0.590 | Hidden |
| 4.0 s | Largest mask component moves to the entrant's head; no current reciprocal proposal | Hidden |
| 5.0 s | Mask covers entrant (diagnostic truth IoU 0.957), p10 0.664 | Hidden |
| 5.5 s | Entrant mask now has p10 0.950 and reciprocal proposal IoU 0.693 | Wrongly 5676 |

Confidence and current detector support can recover on a different animal.
Neither proves that the original biological identity survived the interval of
weak support. The one-slot collision quarantine has no donor/receiver pair to
inspect, and the entire sequence is shorter than its 30-second history window.
This is a causal failure of uninitialized entrants, not a reason to relax a
probability threshold or a correction to the scoring denominator.

A separate births-only control is proposed next: current detector and SAM
evidence may initialize an anonymous stable object before propagation. That
control must have its own freeze; no additions, new thresholds, or outcome
changes are part of this completed baseline.

## Limits

This is a narrow, sequential passage with two animals briefly visible together.
It is useful for actual entry/exit, unlike the six-seed calf control in which
the omitted unknown cows are already visible at time zero. It does not test
dense barn occlusion, independent re-identification, camera reconnection,
re-entry after absence, or sustained memory. These June 8 clips also supplied
the local detector's training images, so later localization results are replay
or adaptation evidence, not unseen-scene accuracy.
