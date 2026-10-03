# Local coat-pattern matching experiment

**Decision: keep this out of the live application.** The measured improvement
does not justify another matching component yet.

The [WildFusion paper](https://arxiv.org/abs/2408.12934) combines global animal
embeddings with local correspondence scores. This experiment uses the existing
OpenCV library for a smaller baseline: RootSIFT in a central crop ellipse, mutual
ratio matches, affine RANSAC and a minimum spatial spread. It is not a
reproduction of WildFusion's learned matcher or score calibration.

Using ten uniformly spaced early photos per known calf, compare oracle crops
every five seconds in both development windows and the separate recognition
calibration window. Thresholds use calibration only. The final video windows
remain unopened. Background and neighboring animals may still contribute
features: an ellipse is not animal segmentation.

Standalone local matching selected at least 11 verified correspondences and a
five-correspondence margin over another cow. It correctly named 40 of 45 accepted
development crops and 25 of 26 later development crops, with only 11.1% and 7.0%
known-cow coverage. Its ten calibration acceptances were all correct. That
calibration result did not generalize well enough.

Adding a weighted `log(1 + inliers)` score to each MIEW reference similarity
helped modestly. Weight 0.2 gave 34.4% and 36.2% development coverage at 99.2% and
98.48% precision. Neither window meets the coverage target, and the later window
also misses the precision target. All seven tested weights, including the
no-local-feature control, are retained in
[the numeric report](results/2026-10-03/local-feature-fusion.json).

The initial CPU extraction and matching took 32.18 seconds for 1,438 query crops
and 60 references. Features are cached by pixel hash and extractor settings.
These are oracle-crop, single-frame diagnostics, not complete camera throughput
or performance with tracking. Adding this component now would increase
complexity without solving the main problem.

## Reproduce

After `recognition_features.py` has produced the development manifest and MIEW
vectors, from the repository root:

```sh
MPLCONFIGDIR=/tmp/cow-identity-matplotlib detector/.venv/bin/python \
  research/cow_identity/local_features.py \
  --manifest .cache/cow-recognition-development/manifest.json \
  --video datasets/8-calves/video/pmfeed_4_3_16.mp4 \
  --output .cache/cow-local-uniform10

detector/.venv/bin/python research/cow_identity/local_feature_fusion.py \
  --features .cache/cow-recognition-development \
  --local .cache/cow-local-uniform10 \
  --output research/cow_identity/results/2026-10-03/local-feature-fusion.json
```

The second command reuses arrays and does no image inference. Reports include
the original manifest hash, score-array hash, reference indices and settings.
