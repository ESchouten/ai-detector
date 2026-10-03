# Foreground and local-pattern controls

The SAM2 foreground control improves the representation but does not meet the
identity goal. It remains research-only. All observations below come from exposed
development/calibration intervals; neither reserved final interval was opened.

## Same photographs, different crops

SAM2.1-tiny receives publisher bounding boxes on the 8-Calves video. Background
pixels become neutral gray. A separate variant rotates the foreground's principal
axis vertically, retaining its 180-degree ambiguity. MIEWid encodes both variants
with its unchanged official weights. The sample contains all 360 early enrollment
photos and every fifth second in the three query intervals: 1,798 crops total.

The primary comparison keeps the **same original diverse ten reference photos**
per animal. Each condition selects similarity/margin thresholds on calibration
only. Known-cow coverage counts every visible enrolled animal in the sampled
oracle observations, including rejected identities.

| Crop | Early development coverage / precision | Later development coverage / precision |
| --- | --- | --- |
| Original box | 21.9% / 98.75% | 26.5% / 96.94% |
| SAM foreground | 40.8% / 96.08% | 40.1% / 97.96% |
| Foreground with axis alignment | 41.9% / 93.79% | 40.1% / 97.30% |

These are single-image, oracle-box diagnostics, not deployed camera performance.
The [masked](results/2026-10-03/recognition/sam-masked-comparison.json) and
[aligned](results/2026-10-03/recognition/sam-aligned-comparison.json) reports retain
uniform-reference and independently selected diverse-reference controls too.
Each report verifies the original manifest link and feature archive digest.

Visual inspection of actual predicted-box prompts showed useful background
cleanup, but also duplicate masks and fragments when detector boxes overlap or
merge two cows. SAM does not recover a missed animal automatically. It therefore
cannot replace measuring localization and tracking.

The actual mixed-detector crops confirm this limitation. On the complete
300-second development window, foreground MIEW with its own diverse references
and calibration-selected temporal settings correctly names 163 of 1,800 visible
known observations (9.1%). Nineteen additional named boxes cannot be matched to
an annotated animal, giving 89.6% conservative named precision. The calibration
window has 154 correct names and one unmatched name (8.6% coverage, 99.35%
precision). All predicted boxes and missed animals remain in the score; matching
uses one-to-one IoU >= 0.5. See the
[actual-track report](results/2026-10-03/tracked/mixed-masked.json).

## Learned local matching

A bounded control uses official ALIKED-n16 features and LightGlue to compare local
coat patterns after foreground masking. Each crop has at most 256 keypoints;
all 60 enrolled references are compared. Both raw match counts and affine-RANSAC
inliers are retained. The separate research environment adds no app dependency.

This more expensive diagnostic samples ten timestamps per interval, 30 seconds
apart: 239 queries and 14,340 reference comparisons. It took 527.7 seconds on two
CPU threads while another model was training on MPS; this is not isolated latency.
Features are cached by image/model/preprocessing fingerprints.

The best calibration-coverage geometric fusion weight, 0.2, increases early/later
coverage from 31.7%/21.7% to 43.3%/43.3%, but early precision falls to 89.66%.
Larger weights can reject more false names while losing coverage. This sparse
control does not justify adding local matching to the application. Both
[geometric](results/2026-10-03/recognition/aliked-lightglue-fusion.json) and
[raw-match](results/2026-10-03/recognition/aliked-lightglue-raw-fusion.json) reports
include every tested weight and the exact timestamps.

## Dense backbone patches

A second local control takes the unchanged MIEW backbone's final feature grid
before global pooling. It excludes grid cells containing less than 75% foreground,
subtracts a channel mean learned from reference patches only, and finds reciprocal
nearest patch matches. At least four matches across two image quadrants in each
image are required. This uses the same 60 original references and 239 sparse
queries as the keypoint control; no new photos or labels are introduced.

The frozen blend weights were 0, 0.25, 0.5 and 1. Pure local matching has the
highest calibration coverage (48.3%), but early/later development precision is
only 93.3%/96.4%, at 46.7%/45.0% coverage. Each interval falsely names one unknown
observation, from only 20/19 unknown observations. These small samples cannot
establish reliable unknown rejection. No variant meets the target.

Extraction and matching took 60.6 seconds on two CPU threads while other research
was active; 58.9 seconds were feature extraction, which is cached. This control
does not justify more runtime machinery. `dense_pattern_protocol.json` freezes
the recipe, `dense_patterns.py` reproduces it, and the
[complete report](results/2026-10-03/recognition/dense-patterns.json) retains all
weights, image indices, input hashes and counts.

## Reproduction and provenance

`segmentation_features.py prepare` creates content-checked masked/aligned PNGs;
`encode` caches embeddings. `recognition_compare.py BASE CANDIDATE --output REPORT`
replays the fair comparison. `deep_local_matching.py` caches upstream local
features; `local_feature_fusion.py` replays fusion with `--score-field scores` or
`raw_scores`. Exact checkpoints, revisions and input hashes are in the reports.

The implementation uses [Ultralytics SAM2](https://docs.ultralytics.com/models/sam-2/)
and [upstream LightGlue](https://github.com/cvg/LightGlue). The rationale follows
[DazzleCow's foreground acquisition](https://github.com/Phoenix4582/DazzleCowIdentifier)
and [WildFusion's local/global comparison](https://arxiv.org/abs/2408.12934), without
assuming those papers' results transfer to this video. The importance of varied
pose enrollment is also supported by
[Perneel et al.](https://doi.org/10.3390/s25102971): the visible coat pattern changes
with orientation and lying/standing posture. More transforms alone cannot supply
an enrolled view of an animal's unseen side.
