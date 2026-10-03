# Controlled-view enrollment and return: bounded benchmark

This is a frozen complementary experiment, not a replacement for the failed
crowded-scene identity results or evidence that the application is ready for
unattended farm use. The initial inventory used metadata only. Query pixels were
subsequently opened for independent annotation, before model inference, as
documented below. No reserved 8-calves windows were opened.

## Best immediately usable source

The [AutoCattlogger paper](https://doi.org/10.1016/j.atech.2025.101561) studies
overhead views of cows returning from milking in single file. Its larger study
uses four recording days in 2022 and 2023 and human-recorded ear-tag order.
However, the [public data instructions](https://github.com/VADL-Purdue/AutoCattlogger/blob/main/data/readme.md)
link a much smaller sample, not that complete raw-video benchmark.

The existing local archives contain the same nine identified cows on June 8 and
June 9, 2022: nine cut videos per day plus a CSV recording their identities.
Each clip has one principal cow, but the authors warn that another cow can be
partially visible near a boundary. The filenames also encode the cow ID and
original frame range. Those labels must never become inference inputs.

Archive and individual clip hashes are recorded in
[the metadata inventory](results/2026-10-03/purdue-passage-inventory.json).
The two archives total about 442 MB and are already present. Reading archive
headers, CSVs and hashes establishes availability; it does not establish that
labels or crop geometry are correct. The separate local Purdue training/testing
archives contain 460/34 detector images and mask/keypoint annotations. They are
not additional independent identity passages.

## Frozen small protocol

[passage_protocol.json](passage_protocol.json) was frozen before any query
pixels were decoded, SHA-256
`d39b3814ea05e4265c8162582c7bbdced3ca382a0135ed724ce286673709b97f`.
The [source manifest](results/2026-10-03/purdue-passage-manifest.json) contains
78 first-day enrollment samples and 105 later-day query samples at 1 fps.
AVI stream headers establish 30 fps and 1920×1080; no decoding was needed.
The primary control uses the existing YOLO26m-seg/ByteTrack preset and actual
`GalleryIdentifier` policy with official, unadapted MIEWid. It transfers the
current 0.65/0.10 similarity/margin settings without another threshold search.
Finish asynchronous gallery preparation before scored frames, report that
startup cost separately, and reset tracker and identity state between clips.

- **Enrollment:** June 8 only. Seven known cows: 2234, 2238, 5676, 5953, 6079,
  6102 and 6110. Withhold 6109 and 6113 entirely from enrollment and adaptation.
  The two unknowns were selected by the first two SHA-256 values of
  `purdue-passage-candidate-v1:<cow-id>`, before image inspection.
- **References:** at most ten human-confirmed images per known cow, selected
  from that cow's first-day passage. Retain fewer if there are insufficient clear
  views. Record every rejected or corrected proposal and time spent enrolling.
  References must come from actual predicted crops if the result is described
  as an application workflow. Publisher-assisted crops are a separate oracle
  diagnostic.
- **Queries:** all nine June 9 passages, exactly once under the frozen policy.
  Reset tracker and name-persistence state at each clip boundary. Use opaque
  clip names and keep expected IDs only in the scoring process. Never recognize
  by clip order, passage position or the CSV sequence.
- **Primary output:** every displayed name at every 1 fps source timestamp,
  scored with the existing conservative one-to-one IoU >= 0.5 rule against all
  visible annotated cows. Missed detections and rejected crops remain in the
  known-cow denominator. Unmatched named boxes count as errors. A final passage
  decision is secondary and must not conceal earlier wrong names. Publish all
  nine outcomes, latency, wrong-name durations, duplicate tracks and enrollment
  effort. Offline three-crop aggregation is an optional diagnostic, never a
  substitute for the production-policy result.
- **Annotation gap:** principal-passage labels do not label every visible box.
  Before counting frame-level errors, independently annotate any sampled frame
  containing another cow or ambiguous track. Do not automatically label every
  crop with the filename's cow ID. A reviewer may see source footage and the
  publisher labels, but should not see model predictions while creating truth.

This gives only seven known and two unknown independent return passages.
Even perfect outcomes cannot establish 99% precision or a 1% unknown error rate.
Foundation-pretraining overlap is also unresolved. Once inspected, this sample
becomes development data; it must not be repeatedly called a blind test.
No previous use of these sample filenames was found in the inspected repository
reports/scripts. That limited search does not certify that nobody previously
viewed the downloaded footage outside the recorded experiments.

A result that succeeds here but fails in the barn would support a narrower
passage-camera workflow. It would not justify assigning these names to remote
mounting/calving events without separately validated camera-to-camera identity.

## Independent annotation before query inference

[The frozen annotations](results/2026-10-03/purdue-passage-annotations.json)
cover all 105 sampled frames, including empty images. SHA-256:
`a3da09f93b8f5182d23b9643aa54634508c7521f374ea526ca54c51db76b94cf`.
These are **AI-reviewed labels**, not externally validated human ground truth.
One agent inspected all source frames without predictions; a second independently
checked the ambiguous border cases, an upper-gate animal, and a principal-cow
sequence. The publisher CSV identifies the principal passage animal only.

Visible head, torso, limbs and tail are bounded in native 1920×1080 coordinates;
shadows and inferred invisible body extent are excluded. There are 46 known-cow
instances, 10 withheld-principal instances, and 20 uncertain nuisance fragments.
Six known and one withheld-principal instance are also uncertain: severe motion
blur makes a trailing tail/hoof difficult to distinguish from shadow. The tiny
stationary upper-left fragment in the 6110 clip might be a hoof or an unrelated
object. Its nine instances are explicitly uncertain, never assigned a biological
ID. An unidentified animal behind the upper gate and a preceding animal leaving
the passage are also retained.

Report the full conservative denominator **and** a definite-only sensitivity
analysis. Separate withheld principal cows from nuisance fragments so many tiny
uncertain fragments cannot make unknown rejection look stronger. No uncertain
box is silently dropped from the primary result. All decoded-pixel hashes,
principal IDs, timestamps and box bounds were checked against the frozen source
manifest. Annotation overlays remain in `.cache/cow-passage-annotation/`.

The publisher's separate COCO photos cannot supply this complete truth: only
four of the nine query cows have corresponding labeled photo examples, their
annotations describe torso masks/keypoints, and no reliable video-frame mapping
is provided. A filename suffix of `12` denotes `dataset_id`, not frame 12.
Labels were therefore not copied from those examples. Query images are now
held out from model selection, rather than being described as unseen by the
annotators. The seven-known/two-unknown cohort remains a small feasibility check.

## Why the other available datasets do not create a fresh test

| Source | Useful evidence | Limitation for this next step |
| --- | --- | --- |
| MultiCamCows2024 | Existing chronological multiview comparison; raw CCTV exists | Already extensively explored here. Curated crops are not complete passages or actual detector tracks. |
| ETHZ adult tracking | Good adult localization; genuine later-day and infrared failures | Already exposed, with incomplete visible-cow annotation and two excluded frame-alignment cases. Keep as regression evidence. |
| SideViewCows2026 | Fixed parlor viewpoint and long time span; publisher timestamps and masks | Already benchmarked, and much of its identity cohort was used in the new public adaptation study. Cannot be relabeled fresh held-out data. |
| MmCows | Public identity-labeled barn images and a cow gallery | Labeled visual data covers one day; larger multiday sequences do not automatically provide independently verified multiday identity truth. Not a passage dataset. |
| MOUNT-Cattle | Local detection and anatomical keypoint labels | No biological identity or recording-time fields; does not supply identified return videos. |
| Recent four-camera corridor study | Explicit passage-disjoint and cross-installation protocols | Study data, splits and checkpoints are available on request, not in a public archival download. Cannot run it autonomously now. |

Primary source records: [MultiCamCows2024](https://doi.org/10.5523/bris.2inu67jru7a6821kkgehxg3cv2),
[SideViewCows2026](https://doi.org/10.5281/zenodo.21605650),
[MmCows](https://github.com/neis-lab/mmcows), and
[the corridor study](https://doi.org/10.3390/a19080675).
The project's [existing benchmark](BENCHMARK.md),
[historical SideView assessment](../../reports/cow-id/2026-09-13-miewid/README.md)
and [ETHZ assessment](ETHZ_ASSESSMENT.md) document prior exposure and limitations.
No new bulk downloads or author messages were made.

The local MmCows crop archive contains 427,390 JPEGs for 16 IDs. Filename
timestamps span July 25 07:57:26 to July 26 04:57:11 UTC, which is entirely
July 25 in the farm's US-Central time zone. Splitting at UTC midnight would
misrepresent one labeled recording day as an independent later-day test.
Only crop/gallery archives are present locally, not complete annotated videos.
MOUNT's 3,427/428/429 train/validation/test records contain cow/pose categories
and occluded/keyframe attributes, but no animal identity, source-video or
timestamp field. These metadata checks did not decode either dataset's images.

## Practical farmer guidance to evaluate, not promise

Use an existing route through which cows naturally pass individually, such as
the exit from milking. A fixed overhead camera is the closest match to this
public control. Show the whole torso clearly near the center of the image,
avoid rails across its markings, strong backlight and motion blur, and keep the
same camera/viewpoint for enrollment and later recognition. Do not prescribe an
unvalidated mounting height or pixel threshold as a guarantee.

The [authors' filtering guidance](https://github.com/VADL-Purdue/AutoCattlogger/blob/main/docs/FAQs.md)
supports using central, complete views rather than partially entering animals.
Their custom-data workflow also requires detector/keypoint adaptation; its
reported results cannot be treated as a ready-made guarantee for our model.

The simple application flow would remain: choose a camera in setup, inspect its
live preview, then confirm the number/name against clear Herd photographs.
Camera guidance belongs beside that preview, not in another configuration
wizard. Automatically collected photographs remain unconfirmed until reviewed.
If the cow is clipped, obscured, seen from an unenrolled view or ambiguous,
display unknown rather than infer a name from the previous passage.

Before a broader farmer trial, collect a new independently labeled cohort with
multiple physical return passages across days, unknown cows, night/IR changes
and occasional overlapping animals. Freeze enrollment, calibration and final
recordings by whole passage and day before model development. A farmer-confirmed
ear-tag record or independently recorded RFID may establish truth, but must not
enter a benchmark advertised as camera-only inference. The small public sample
can expose a basic failure cheaply; it cannot replace this validation.
