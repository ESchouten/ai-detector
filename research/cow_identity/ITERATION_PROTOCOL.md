# Working protocol: useful identification on video

Frozen on 3 October 2026 before the new detection, enrollment and matching
experiments. This continues the failed baseline in [VIDEO_ASSESSMENT.md](VIDEO_ASSESSMENT.md).
Passing software tests or rejecting every animal does not satisfy the goal.

## Acceptance targets

For the complete pipeline on reserved video, report both per-window and pooled:

- At least 99% of assigned names correct, with raw counts and uncertainty.
- At least 60% correct naming coverage of visible enrolled animals. Missed
  detections and rejected crops remain in the denominator.
- At most 1% of visible withheld animals incorrectly given an enrolled name.
- Measured bounded processing time on MPS, including detection, crop extraction,
  encoding, matching and tracking. Do not equate an encoder benchmark with the
  number of live cameras supported.

Matching to annotation boxes is one-to-one at IoU >= 0.5, maximizing cardinality
before IoU. Separately report unmatched detections, track identity switches,
localization recall, crop eligibility and recognition using oracle boxes. A named
unmatched detection is not evidence of a correct name. Publish those counts too.

The intended product is a farmer-confirmed gallery, with at most ten varied
enrollment photos per animal in the first experiments. Publisher IDs simulate
human confirmation. Reference photos and unknown animals must never be added
from final evaluation. Unknown is a valid result; low coverage is still a failure
to reach the target.

## 8-calves split

Use the original `pmfeed_4_3_16.mp4` (20 fps, 67,760 frames) and independently
audited publisher annotations. Calves 1–6 are enrolled; calves 7–8 are unknown.

| Seconds, inclusive | Role | Allowed use |
| --- | --- | --- |
| 0–299 | Enrollment / adaptation | Choose up to ten useful examples per known calf; detector training may use all cow boxes with identity removed. |
| 330–629 | Development | Error analysis and method selection; already exposed by the baseline. |
| 630–899 | Detection calibration | Compare detector checkpoints and training choices. |
| 930–1229 | Development | Second exposed window for stability and error analysis. |
| 1230–1529 | Recognition calibration | Set rejection thresholds and temporal policy. |
| 1800–2099 | Reserved evaluation | Open only after the complete method and settings are frozen. |
| 2700–2999 | Reserved evaluation | Same frozen method; no retuning between windows. |

Recognition training excludes unknown identities. Detection-only training may
include all calves because it learns the cow category, never their names. No
identity-classification checkpoint trained on the reserved unknown identities
may be counted as an open-set recognizer.

Evaluate at one-second timestamps for comparable counts. Tracking experiments
may process intermediate frames, but scores use exactly the same timestamps.
Trackers and temporal identity state reset between disconnected windows. Online
decisions may use only current and previous frames, never future observations.

This is a temporally separated test in one previously studied public recording,
not an independent farm or a guarantee for adult cows, nights, different breeds
or cameras. If the method fails, retain the failed result and make the next
development/evaluation distinction explicit. Do not silently recycle a test as
an untouched holdout.

## Independent checks and efficiency

- Verify annotation conventions against the original publisher data before
  training. Keep that audit separate from the implementation being evaluated.
- Compare localization and recognition independently before combining changes.
- Cache detector predictions and image embeddings with source hashes, model
  hashes, library versions and preprocessing settings.
- Reuse cached arrays for CPU-only parameter comparisons. Run one heavy MPS job
  at a time to make timings interpretable.
- Preserve failed approaches with concise evidence; do not add unproven
  machinery to the application.
- Use the adult ETHZ videos as a separately labelled cross-day regression after
  the development method is selected. Those data were studied in earlier local
  work, so call them an external-scene regression, not a pristine blind test.

The active goal stays open until the video criteria and their application
integration are demonstrated. Any eventual result must state its exact scope.
