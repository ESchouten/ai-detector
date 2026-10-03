# Continuous tracking: the reserved evaluation failed

The frozen method passed its first reserved panel, but failed the second and the
pooled precision target. It must not be presented as a reliable unattended cow
identity system. The failures remain in the original counts, including boxes
whose names cannot be matched to a publisher annotation.

| Previously reserved panel | Correct / visible known | Coverage | Conservative precision | Wrong known / unknown named / unmatched named | All gates pass |
| --- | ---: | ---: | ---: | ---: | --- |
| 1800–2099 seconds | 1123 / 1799 | 62.42% | 99.293% | 0 / 0 / 8 | Yes |
| 2700–2999 seconds | 1303 / 1781 | 73.16% | 97.970% | 0 / 0 / 27 | No |
| Both panels, summed counts | 2426 / 3580 | 67.77% | 98.578% | 0 / 0 / 35 | No |

The fixed gates were at least 99% conservative precision, at least 60% correct
naming coverage and at most 1% false naming of unknown animals, separately for
each panel. Unknown naming was 0/591 and 0/512. Pooling sums counts rather than
averaging percentages. Zero wrong names among matched boxes does **not** remove
the 35 unmatched named errors. These are correlated observations of six initially
named calves and two anonymous calves, not thousands of independent animals.

The immutable [strict report](results/2026-10-03/detection/cutie-streaming-reserved.json)
contains every count and acceptance Boolean. It records 4683 visible annotations,
4511 matched boxes, 172 missed annotations and 287 unmatched predictions. No
operating point was changed after opening these panels.

## What was fixed before the trial

The [selection](detection_reserved_selection.json) was saved before decoding any
new frames. The [execution](detection_reserved_execution.json) and
[evaluation](detection_reserved_evaluation.json) bind the actual files, source
pixels, models, scoring helpers and successful application-runtime development
test. The source checkpoint is `468b29e`; recorded hashes identify the exact
historical implementation independently of subsequent branch changes.

One reviewed frame-zero detector proposal per calf initialized the existing
SAM/Cutie masks. Cows 1–6 were named and 7–8 remained anonymous. Cutie then ran
continuously from second 0 through 2999 at two input frames per second, without
additional prompts, future labels or resets between scoring panels. The initial
frame belongs to the localization training interval, so initialization remains
optimistic. This is continuous same-camera tracking, not recognition after a
restart, departure or another day.

The policy was unchanged: original largest-component boxes; mask probability
at least 0.70; causal collision quarantine and three-observation recovery from
current geometry; distinct reciprocal raw-YOLO partners at IoU at least 0.50.
Both networks ran in one application PyTorch process on MPS, Cutie in FP32 and
YOLO in FP16. The recorded decisions, rather than a later reconstruction, were
scored by the existing one-to-one IoU evaluator.

The [prefix verification](results/2026-10-03/detection/cutie-reserved-prefix-parity.json)
found exact equality with development for all 3059 shared source frames and all
1530 integer-second output rows: original masks, raw detector boxes,
largest-component boxes, confidence summaries, reciprocal pairs, names and
conflicts. All 3060 corresponding mask files matched their recorded hashes.
The late failure therefore is not explained by a changed early initialization
or source decode.

## Runtime

All 5999 inputs completed without a resource stop or inference exception in
978.47 seconds. Mean input processing was 158.3 ms, p95 226.3 ms and p99 251.3 ms.
Three inputs exceeded the 500 ms sampling interval; after excluding the first,
two of 5998 did. Steady p95/p99 were 226.2/250.9 ms.

Observed Metal driver allocation peaked at 6.684 GiB before cache reclamation
and 5.999 GiB afterward; peak process RSS was 1.184 GiB. Working/long-term memory
maxima were 10800/9984 tokens. These are observed maxima, not a promise that a
cache compaction target is a hard limit. Mean throughput fits this one-camera
trial; this does not establish multi-camera or installer performance. A first
launch in the restricted process environment stopped because MPS was unavailable,
before model inference; the unchanged run succeeded with the same host access
used by the development experiment.

## Why the names failed the strict test

The [geometry audit](results/2026-10-03/detection/cutie-reserved-error-audit.json)
and [per-frame visual review](results/2026-10-03/detection/cutie-reserved-error-review.json)
retain all 35 errors. Source pixels and indexed masks were rehashed before
rendering. No frames at or beyond second 3000 were decoded.

- In 33 cases the named calf has a publisher box. Its mask rectangle has IoU
  0.288–0.498 with that box; none loses a valid match to another predicted slot.
  Seventeen sit between 0.45 and 0.50, but the original 0.50 cutoff is retained.
- Twenty-nine rectangles are smaller than their own publisher box; twenty lie
  wholly within it. The visible mask often covers the narrow coat-bearing body
  while the publisher box includes a broader silhouette or loose extent.
- The already paired independent detector box reaches own-calf IoU 0.50 in
  29 of those 33 cases. This is a diagnostic comparison, **not** a rescored or
  promoted output policy. The detector also fails some crowded or loose-extent
  examples, and replacing all output geometry could introduce other errors.
- Only six masks have disconnected pieces; the largest piece retains at least
  97.9% of area. Small islands are not the main explanation in this selected
  error set. Crowded-frame extent ambiguity remains visible, particularly at
  second 1889. Still images do not prove that every retained identity is correct.
- At seconds 2770 and 2790 the emitted cow-4 region contains a clearly visible
  animal, but the publisher has no cow-4 box. This motivates independent
  annotation review, not favorable relabeling after seeing predictions. Both
  remain unmatched named errors.

The errors concern cow 6 twelve times, cows 4 and 5 six times each, cow 3 five
times, cow 1 four times and cow 2 twice. The source contact sheets and all
35 native overlays remain in ignored local storage at
`.cache/cow-cutie/reserved-error-audit/`; the tracked report contains their hashes.
The first audit renderer halted because it compared copied detector confidence
with a mask helper's constant confidence. A separately recorded second freeze
compares the actual geometry only; three regression tests pass. Neither attempt
changes the inference or strict report.

## What remains open

Seconds **1800–2099 and 2700–2999 are now exposed development data**. The original
failed reserved result stays unchanged. Any later geometry control must be
reported as further development, not as rescuing this holdout result. Seconds
**3000 through the end remain closed** for a separately frozen future test.

The historical [continuous protocol](CONTINUOUS_TRACKING_PROTOCOL.md) remains
byte-identical because it is part of the frozen provenance; this document records
its completed outcome. Next work should isolate the output-geometry problem,
then test new arrivals, departures and restarts without automatically inheriting
an old name. Independent multi-day farm validation is still necessary even if a
later single-recording control meets all numerical gates.

## Subsequent exposed-data control: raw detector output also fails

A separately frozen [geometry control](detection_output_geometry_protocol.json)
then retained every recorded name/pair/gate but returned every actual raw detector
proposal, with names only on the corresponding unique confirmed proposals. This
is a new development experiment. Baseline counts reproduce exactly. Precision
falls to 95.49–97.00% across all five exposed panels, including 6 wrong-known and
7 unknown-animal names overall. All five fail. The [report](results/2026-10-03/detection/cutie-output-geometry.json)
retains false and duplicate proposals and the full one-to-one matching
denominator. A detector that improves selected bad mask rectangles can still
worsen global naming/localization. No part of this result rescues the original
reserved failure, and the remaining closed interval has not been accessed.

The subsequent [global diagnosis](results/2026-10-03/detection/cutie-output-geometry-diagnosis.json)
separates two causes: 133 previously correct names lose valid own-cow geometry;
82 valid boxes instead lose their global assignment, including 81 taken by an
additional unpaired raw proposal. A separately frozen original-slot rectangle
union tests both mechanisms without adding proposals or shrinking the mask
extent. It also [fails every exposed panel](results/2026-10-03/detection/cutie-union-geometry.json),
with precision 96.82–98.80%. Both geometry controls are rejected. No further
geometry condition or newly reserved interval was evaluated.

## Clean-image review: extent disagreement is not automatically mask failure

A [second qualitative review](results/2026-10-03/detection/cutie-reserved-physical-review.json)
compares all 35 clean source images with their masks and rectangles. In 25 cases
the mask appears to cover a near-complete visible animal while the publisher
rectangle includes appreciably more floor or neighboring extent. Five publisher
rectangles appear partial or shifted, three crowded cases remain ambiguous, and
two have no own annotation. These are selected-error interpretations, not
independently certified biological identities or replacement labels.

At 2877 and 2895 seconds, isolated animals have coherent masks including most
visible anatomy; their low box IoU is not evidence that half the animal was lost.
The [dataset paper](https://arxiv.org/html/2503.13777v2) states that video labels
were created with a fine-tuned YOLOv8m/ByteTrack pipeline and manual corrections;
it discloses missing boxes and detector bias. It does not define a consistent
manually traced modal/amodal mask policy. Therefore another segmentation model
is not justified solely by these low rectangle IoUs.

The next diagnostic is a separately frozen, uniform clean-frame sample across
the five already exposed panels, independently annotated without seeing model
or publisher overlays. It must include every visible animal and keep uncertainty,
not repair only the 35 failures. Original strict metrics remain unchanged; no
alternative pass score is implied.
