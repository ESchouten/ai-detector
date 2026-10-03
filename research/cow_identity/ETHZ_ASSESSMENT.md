# Adult-cow cross-day assessment, 2026-10-03

The author's cattle detector locates almost all annotated adult cows in these
short barn panels. The current MIEWid gallery matcher does **not** identify them
reliably across days: with the existing conservative thresholds it accepts no
identities in either later-day panel. Lowering the threshold would conceal the
weak representation rather than establish a useful recognition system.

This is a separate adult-cow scene from 8-calves. The project previously studied
these public ETHZ videos, so this is an external-scene regression, **not a blind
test, farm validation, or end-to-end identity result**.

## Sources and frozen panels

The [author's repository](https://github.com/meiqing-wang/Cow-TrackingbyClassification)
and [ETHZ dataset record](https://doi.org/10.3929/ethz-c-000796658) describe 13 cows,
classification crops, detection data, and six tracking videos. Tracking label
classes denote individual cows; ordinary detection class labels do not. The
dataset's noncommercial-use permission and the source code's license are separate;
we retain downloaded data, crops, and weights locally rather than redistribute them.

The historical source inventory is
`reports/cow-id/2026-09-13-ethz-video/dataset-and-method.md`. Our new bounded protocol
is [ethz_protocol.json](ethz_protocol.json), SHA-256
`1574a8e20661cd38694732d43ad57ea5dd331fe8828e9475e18d736bb515d901`.
It was frozen before this run's inference. No threshold or reference selection
was adjusted after inspecting the later-day results.

Enrollment uses the historical 109 hash-pinned publisher classification crops
from August 23, selecting at most ten per identity by evenly spaced indices in
camera/path order. This gives 97 references for ten identities: 0, 1, 5, 6, 7, 8,
9, 10, 11, and 13. Identity 11 has only seven references. IDs 3, 4, and 12 remain
unenrolled. References were not selected using query scores or corrected using
the evaluation labels.

| Video | Date | Physical camera | Role | Container frames / labels | Sampled frames / annotations |
|---|---|---|---|---:|---:|
| 3 | August 25 | 195, color | Earlier-day calibration panel | 27,030 / 27,030 | 30 / 210 |
| 4 | August 24 | 197, infrared video | Earlier-day calibration panel | 22,512 / 22,512 | 33 / 111 |
| 5 | September 17 | 195, color | Later-day regression | 54,036 / 54,036 | 30 / 230 |
| 6 | August 28 | 197, infrared video | Later-day regression | 45,025 / 45,025 | 33 / 385 |

Each video contributes three approximately ten-second windows beginning near
0, 30, and 60 seconds. The precise source indices and sampling strides are in
the protocol. Decoding is sequential from zero; normalized center-XYWH labels
in `frame_000000.txt` refer to decoded source frame zero. We checked all label
indices for continuity, recomputed source hashes, and inspected the four first
frames with both truth and actual predictions. Alignment and dates were correct.
Videos 1 and 2 remain excluded because container/label counts disagree
(4,518/4,501 and 4,154/4,146). We did not guess an alignment correction.

## Localization is strong in this adult scene

The author's YOLOv8s checkpoint, 640-pixel input, FP16 on MPS, was evaluated on
the same 126 source frames. At confidence 0.25 and one-to-one IoU >= 0.5:

| Video | Matched annotated cows | Annotated recall | Unmatched predictions |
|---|---:|---:|---:|
| 3 | 198 / 210 | 94.29% | 3 |
| 4 | 101 / 111 | 90.99% | 23 |
| 5 | 222 / 230 | 96.52% | 2 |
| 6 | 383 / 385 | 99.48% | 17 |

The publisher's labels are not exhaustive: visible foreground cows in video 4
are unlabelled, for example. Consequently unmatched predictions are **not
reported as false positives**, and these panels do not establish precision.
The separate confidence-0.10 result is preserved in the JSON without selecting
the threshold that makes the summary look best. No identities are assigned by
this localization assessment. The same checkpoint's failure on calves therefore
cannot be explained simply by a broken model file.

## Oracle recognition still fails across days

Oracle crops use publisher boxes, not detector predictions. The production MIEWid
FP32 encoder generated 1,033 fresh embeddings on MPS in 24.46 seconds, excluding
model startup and source-frame decoding. Matching takes the best reference cosine
per distinct identity, with unchanged minimum similarity 0.65 and margin 0.10.

| Video | Known / unknown observations | Known rank-1 | Correct accepted / known | Wrong accepted |
|---|---:|---:|---:|---:|
| 3 | 160 / 50 | 91.25% | 30 / 160 (18.75%) | 0 |
| 4 | 111 / 0 | 52.25% | 22 / 111 (19.82%) | 0 |
| 5 | 200 / 30 | 32.00% | 0 / 200 (0%) | 0 |
| 6 | 286 / 99 | 43.36% | 0 / 286 (0%) | 0 |

Wrong accepted includes either an incorrect enrolled name or an accepted unknown
cow. Zero errors with zero coverage is a failed useful-identity result, not proof
of accuracy. Video 4 has no unknown animals, so its unknown false-acceptance rate
is undefined. Neighboring observations are correlated; counts are not independent
trials and provide no farm-scale false-acceptance guarantee.

A second diagnostic adds crop geometry, collision rejection and three increasing
timestamp samples using oracle continuity. Correct accepted coverage falls to
10.0% and 16.22% in videos 3 and 4, and stays zero in 5 and 6. This uses production
geometry/temporal policy functions but is **not an exact runtime replay**: it
supplies ground-truth track IDs, resets each window, and samples IR frames about
0.96 seconds apart without the runtime's one-second sampling gate. It cannot
establish tracker accuracy or compensate for weak embeddings.

## Identity-label and camera audit

After observing the weak later-day results, we visually compared gallery and
query crops for six identities: 0, 5, 8, 10, 11, and 13. Distinctive coat patterns
were consistent with the publisher IDs in these samples; we found no obvious
label remapping. This is a bounded visual check, not a relabeling of the dataset.
Examples contain standing versus lying bodies, head-on/top versus lateral views,
deep shadows, stall bars, and neighboring cows inside the crop. These are plausible
recognition difficulties, not isolated causes established by this experiment.

Using the same cached vectors, we separately restricted enrollment to the query's
physical camera or the other camera:

| Video | All-gallery rank-1 | Same-camera rank-1 | Other-camera rank-1 |
|---|---:|---:|---:|
| 3 | 91.25% | 91.25% | 19.38% |
| 4 | 52.25% | 42.34% | 33.33% |
| 5 | 32.00% | 36.00% | 32.50% |
| 6 | 43.36% | 41.61% | 30.07% |

Both restricted galleries still contain all ten identities, but they have 50 and
47 references, respectively, with unequal views per cow. This is a diagnostic,
not a controlled camera-effect estimate. Same physical camera does not imply the
same flank, pose, or lighting. The historical camera-197 alias contains the word
`infrared`, but a few classification references from that camera are color images.
We did not infer image modality from that alias. No camera restriction produces
accepted identities in videos 5 or 6, so camera filtering alone does not solve the
observed cross-day failure.

## Reproduce and inspect

Run from the repository root, using the dataset paths and hashes in the protocol:

```sh
detector/.venv/bin/python research/cow_identity/ethz_oracle.py prepare
detector/.venv/bin/python research/cow_identity/ethz_oracle.py encode --device mps
detector/.venv/bin/python research/cow_identity/ethz_oracle.py score
detector/.venv/bin/python research/cow_identity/ethz_localization.py --device mps
detector/.venv/bin/python research/cow_identity/ethz_gallery_audit.py
detector/.venv/bin/python -m pytest -q research/cow_identity/test_ethz_assessment.py
```

`--weights` can point the encoder at the already downloaded pinned MIEWid file.
The author detector is expected at `.cache/cow-detectors/ethz-yolov8s.pt`; its hash
is recorded in the compact localization summary. Enrollment images currently
follow the historical extraction tree named in the protocol. Dataset/model files
are not bundled with the repository.

Scripts verify source/feature provenance and cache embeddings by content. Raw
cropped images, vectors, source frame overlays and identity montages remain under
`.cache/cow-ethz-oracle*` and `.cache/cow-ethz-localization`. Compact results are
committed under `results/2026-10-03/ethz-{oracle,localization,camera-audit}.json`.

The next promising recognition experiment is controlled, varied enrollment and
calibration on earlier-day data, with training strictly separated from later
queries. The current evidence supports the author's adult detector as a useful
candidate, but does not support shipping automatic adult identity decisions.
