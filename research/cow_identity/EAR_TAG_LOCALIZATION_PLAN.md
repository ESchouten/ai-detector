# Head and ear-tag localization: bounded pilot and failed generalization

2026-10-03: source inventory, a fixed oracle-geometry check, reviewed training
annotations, and one completed two-class head/tag training and evaluation pilot. The original
three-class whole-frame proposal was not run because most whole-body annotations
were incomplete. The executed pilot used 13 reviewed foreground ROIs; its
validation reused those same training images and proves no generalization.
The subsequent fixed full-frame test found no matched development tags and
12 of 33 outdoor tags. This model is not ready for automatic ownership.

Existing cow detection/tracking could supply body candidates later. Ownership
remains an explicit, abstaining relation that must be tested separately.
Reading a correct number in a crop is insufficient if it is assigned to the
neighboring cow. This experiment tests that boundary; it does not change the
running TrOCR experiment or merge anonymous profiles.

## Verified source investigation

| Primary source | Relevant method | Reusable author artifact found |
| --- | --- | --- |
| [Gao et al., Sensors 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11014036/) | Small-YOLOv5s tag detector followed by DBNet/CRNN; releases CEID-D and CEGD-R data. | Author-linked Kaggle data, already cached. The paper's data-availability links do not provide trained detector weights or detector source. No verified weight download found in the checked author/paper paths. |
| [Smink et al., ReadMyCow, WACV 2024](https://openaccess.thecvf.com/content/WACV2024/html/Smink_Computer_Vision_on_the_Edge_Individual_Cattle_Identification_in_Real-Time_WACV_2024_paper.html) | Fine-tuned YOLOv5s locates tags; tag tracking and WhenToRead select readings over time. | CVF lists the paper, not a downloadable model/code artifact. An [author announcement](https://www.linkedin.com/posts/moniek-smink_wacv2024-computervision-researchpaper-activity-7149907839270985728-5phf) links paper/poster/presentation. No verified public detector checkpoint located. Its output is tracked tag boxes, not demonstrated crowded tag-to-body ownership. |
| [Bastiaansen et al., Frontiers 2022](https://www.frontiersin.org/journals/animal-science/articles/10.3389/fanim.2022.846893/full) | Camera-specific yellow-color tag localization and a retrained house-number reader in a milking-robot setup. | Linked generic SVHN code is a digit reader, not an ear-tag detector checkpoint. Controlled single-animal camera geometry does not validate crowded ownership. |
| [Automated Cattle Head and Ear Pose Estimation, 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12300177/) | Mask R-CNN head/left-ear detection plus pose estimation, with separate cattle for testing. | Data are available on request; no author weight download found. This detects anatomy, not tag-to-whole-cow relations. |

These bounded searches do not prove that no public checkpoint exists. They avoid
silently treating an unrelated community model as an author-released, validated
ear-tag detector. No emails were sent. The cached official Ultralytics COCO
YOLO11s is a transparent starting point, **not** an already trained tag detector.

## Existing data and proposed split

`eartag_localization_inventory.py` verifies all 32 original image hashes, decoded
sizes and published tag geometry, records EXIF plus original/decoded hashes,
checks exact pixel duplication, and writes
`results/2026-10-03/ear-tags/localization-preparation.json`. It calls no models.

The 29 published label files contain 125 tag rectangles only. There are no head
instances, body instances, ownership links, transcripts or certified biological
IDs. `cow172`, `cow431` and `cow1811` remain unannotated, never empty negatives.
The previous visibility review and published tag rectangles were already exposed;
this is a development study, not a newly blind source dataset.

Ten Xiaomi files retain March 1, 2023 timestamps; five retain March 22 dates.
Sixteen have no timestamp. The Sony frame has a January 1, 2008 factory-like date
that cannot establish capture chronology. EXIF is provenance evidence, not a
certified timeline. The source inventory's `shape` is explicitly **width,height**.

| Proposed role | Scene group | Labeled images | Tags |
| --- | --- | ---: | ---: |
| Training | Indoor feeding/pen views | 18 | 81 |
| Development diagnostic | Three undated 640×368 camera frames, kept together | 3 | 11 |
| Evaluation | All outdoor views, including March 1 `cow1207` and both undated portrait views | 8 | 33 |
| No supervision/scoring | Missing tag labels | 3 | Unknown |

The exact IDs and hashes are in the preparation JSON. Do not distribute derived
tiles, augmentations or neighboring views across these groups. The outdoor
scene is kept out of training even though `cow1207` has an earlier timestamp.
This split is **not date-, farm- or animal-disjoint**: the same farm/cows may
appear indoors and outdoors, and March 1 spans both scenes. The low-resolution
development group may depict the same indoor location/animals. Do not use it to
choose thresholds or report independent validation. An independent reviewer
must verify the visible scene grouping before execution. More data would be
needed to establish performance across farms or camera installations.

## One bounded pilot to freeze after annotation review

1. Annotate all visible cow heads and whole visible bodies in the 29 labeled
   frames, including animals without a visible tag. Preserve every published
   tag box and add a tag→head→body link only when the physical connection is
   visually clear. Use local image-instance IDs, never a guessed ear number.
   Record occlusion, cropped bodies and ambiguous ownership explicitly; no
   inferred hidden extent. Review clean pixels independently of predictions.
   The three unlabeled images require a complete separate annotation pass if
   they are ever added; this pilot excludes them.
2. Train the cached official COCO YOLO11s once for the three detection classes.
   Initial SHA256 is
   `85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5`
   (`.cache/cow-video-policy-cache/yolo11s.pt`). Proposed fixed recipe: 20 epochs,
   batch2, image size1280, FP32 MPS, seed17, AdamW learning rate0.0001,
   weight decay0.0005, no mosaic/mixup/copy-paste, no early stopping or model
   selection. Keep the final checkpoint, all training logs and the exact
   installed-library/config hashes. Stop and record an incomplete pilot if
   elapsed training exceeds10minutes or MPS driver memory exceeds8GiB; do not
   silently lower resolution or change parameters. This is a small-data
   feasibility test, not evidence that eighteen photos suffice for deployment.
3. Run all development/evaluation whole frames once with confidence0.25,
   class-aware NMS0.7, no test-time augmentation, and reversible letterbox
   coordinates. Keep all raw outputs before scoring. Detection input is the
   whole image; any OCR crop later comes from the original decoded source, not
   an enlarged thumbnail. Report tag recall separately by native tag size and
   actual detector-input tag size. Tiny unreadable tags remain in the detection
   denominator.
4. For a deliberately simple first ownership rule, require at least90% of a
   predicted tag rectangle inside exactly one predicted head rectangle, and
   at least90% of that head inside exactly one whole-cow rectangle. Otherwise
   abstain. Multiple tags may share the same head; do not force a one-tag-per-cow
   rule. Never choose the nearest body or use OCR digits to select the owner.
   This rectangle rule may abstain heavily in crowds and is not anatomical
   proof. Score its failure honestly before considering a more complex model.

No checkpoint-selection grid, extra reader or iterative threshold search belongs
to this pilot. Annotation/source review and an immutable execution protocol are
required before training. The training recipe above is a proposal, not an
executed frozen run.

## Scores and useful failure decisions

Use one-to-one IoU≥0.5 matching for each localization class, counting all misses,
duplicate outputs and extras. Ownership is correct only when tag, head and body
all match the independently linked instances. Report accepted wrong owners and
accepted unverified/ambiguous owners separately and conservatively together in
the claimed-binding precision denominator. Report correct links over all
published tags, plus a separate clearly-assignable subset; never replace the
full denominator with that easier subset.

Also compute an explicitly labeled oracle-box diagnostic using annotated boxes
with the same rectangle rule. If even correct boxes cannot establish unique
ownership, more tag-detector training cannot solve that case. If tag localization
fails, the next data requirement is varied grouped whole frames; if ownership
fails, head/body masks or temporal attachment evidence must be evaluated before
automatic naming. An ear-tag tracker alone is not a cow tracker.

The existing OCR crop dataset derives from the same author collection. Its
potential overlap with these whole frames prevents calling an end-to-end OCR
result independent. This pilot therefore measures localization/ownership only.
Static frames cannot establish repeated independent reads, continuity, exit and
re-entry, or safe anchoring of an entire long-lived anonymous profile. Any later
number evidence must bind only to the current verified camera episode.

## Fixed three-frame ownership feasibility result

After independent review of all six head/tag/body overlays, the annotations,
three original source images, exact rule and scorer were frozen in
`eartag_ownership_oracle_protocol.json` (SHA256
`b49d1fa03d43b96917eba1d5f6b46be7428d1331e040ad039360d6ebe7540af0`).
All uncertain body rectangles remained competing owners. Synthetic boundary
tests confirmed exact90% containment, abstention for competing bodies/heads,
truth-independent prediction and separate unknown-attachment accounting.

The unchanged rule correctly links **10 of11 published tags**, abstains on one,
and makes no verified wrong tag assignment in this small oracle sample. The
abstention is `cow1983/T3`: its head fits both the intended white cow B3 and
the overlapping uncertain B2 fragment. Choosing the nearest body would have
hidden this ambiguity. All11tags/all12heads/all20body rectangles remain in
`results/2026-10-03/ear-tags/ownership-oracle.json`.

Across all12heads, ten body links are correct, one abstains and one is
**accepted but unverified**: cropped `cow1983/H6` geometrically selects B8, while
the reviewed physical attachment remains unknown between B8/B9. No published
tag belongs to H6. Thus the favorable tag result does not establish that unique
rectangle containment proves ownership on every head, and it is far too small
to demonstrate99% precision. Annotation rectangles and relationships are
AI-reviewed approximations, not detector output or independent field labels.

This supports a narrow next step: annotate the18 training images' visible
heads/bodies and freeze the proposed single three-class detector pilot. Keep
the eight outdoor evaluation images out of training and model selection, obtain
their independently reviewed ownership labels before final scoring, and retain
unknown attachments in conservative precision accounting. Do not add OCR/name
assignment yet. No learned localization result or automatic animal identity is
established by this oracle feasibility check.

## Training annotation batch: incompleteness changes the proposal

A bounded clean-pixel annotation batch inspected all 18 proposed training
images. It retained all 81 publisher tag rectangles verbatim and added nine
separately recorded, clearly visible missing tags. The draft contains 51 head
rectangles, 37 visible-body or body-fragment rectangles, and 25 unresolved
regions. The added tags include small background tags, thin side-on tags, and
an occluded tag fragment behind another cow's ear. Ambiguous yellow regions
were not guessed to be tags. No model outputs or evaluation head annotations
were used.

Only `cow258` and `cow345` currently have complete full-frame annotations that
the parent independently reviewed. The latter retains its blur/rail-occlusion
caveat. The other 16 frames are explicitly ineligible for ordinary three-class
full-frame training: unannotated distant heads or cows must not silently become
negative examples. Body ownership is also genuinely unclear in several
crowded images. These are AI-reviewed annotations, not certified human labels.
The original three-class training proposal above was **not run**.

The smaller follow-up proposal is to train just **head and ear-tag localization**
on one predeclared foreground ROI from each of 13 training sources, and reuse
the existing whole-cow detector/continuous tracker as the body candidate source.
The proposed crops contain 25 complete or clipped heads and 42 complete or
clipped tags. Every positive-area intersection is retained and clipped
consistently; no area threshold removes small fragments. The two newly proposed
classes still require independent ROI-completeness review before training.
Excluded sources and exact native-coordinate crops are recorded before any
learned outputs in `ownership-two-class-roi-proposal.json`.

This reduces the new annotation problem to the missing capability without
pretending that a small batch can teach a new whole-cow detector. Ownership
still requires the separate conservative tag-to-head-to-body rule; a detected
head or readable number does not establish a cow identity. Whole-frame
development/evaluation inputs and their complete denominators remain unchanged.
Foreground crops provide limited scene/background diversity and only 13 source
images, so this is a feasibility pilot, not evidence of farm-level generalization.
Any eventual training protocol must also retain a checked CPU/MPS numerical
boundary before using Metal gradients.

The partial annotation, source/image checks, and reviewable clean/numbered crop
paths are in `results/2026-10-03/ear-tags/ownership-training-batch1-draft.json`,
`ownership-two-class-roi-proposal.json`, and
`ownership-training-batch1-review-package.json`. The batch ended after about
13 minutes, below the 20-minute cap. No training or new model inference occurred.

## Executed two-class training pilot

Independent review approved all 13 ROI candidates after a versioned correction
to `cow603`: the original head rectangle omitted part of its visible left ear.
Version 2 expands that head boundary and clips it at the unchanged crop edge.
All earlier annotation/report files remain intact; no published tag changed.

`eartag_localization_training_protocol.json` freezes 390 source/data/model files,
the exact initialized two-class weights, all actual SDK defaults, and the recipe:
official cached COCO YOLO11s, 1280 input, FP32 MPS, batch2/nbs2, 20 epochs,
AdamW at constant 0.0001 with weight decay0.0005, seed17, no warmup, augmentation,
AMP, early stopping or selection grid. Native validation uses batch4 and the
same 13 crops. Explicit `augmentations=[]` prevents the optional library's
default image augmentation. Native data transformation preserved all 25 head
and 42 tag instances. The checked CPU/MPS numerical probe preceded training.

The unmodified native trainer completed **20 epochs and 140 updates in125.05s**.
Peak Metal driver allocation was4.898GB (4.56GiB), and peak process RSS2.528GB,
below the frozen 600s/8GiB limits. Passive callbacks rejected nonfinite loss,
unexpected sources, initialization drift and incomplete/repeated epochs.

The selected artifact is native **last.pt**, SHA256
`5e4eedf093e222aaa20ad18e2b0540d9302d1cad3db7ee0fe602e38d55bfaf3c`.
Its tensors exactly match the final live EMA after the library's documented
FP16 serialization. Subsequent validation explicitly uses FP32; this does not
restore precision discarded during checkpoint serialization. The native
best-checkpoint validation also sees only training crops and does not select
the research artifact.

The final last.pt train-only check gives P0.99353/R0.99853, mAP50=0.995 and
mAP50–95=0.85720. These are **training-set fit metrics**, not the user's named-cow
precision goal, a fixed0.25 operating-point result, ownership accuracy, or
evidence on new animals/scenes. The complete result is
`results/2026-10-03/ear-tags/localization-training.json` (SHA256
`a88272aba67d68ac58582d5183ca32c6a373a9d6c39a307db8676c264bdecb10`).
Development/outdoor evaluation subsequently used the separate frozen protocol
below, with all earlier training and annotation records left unchanged.

## Fixed full-frame evaluation: not suitable for deployment

`eartag_localization_evaluate_protocol.json` bound 361 input/source files before
the first inference on the three low-resolution development frames and eight
outdoor frames. The selected final checkpoint was unchanged. Inference used
FP32 MPS, 1280 input, batch 1, confidence 0.25, NMS IoU 0.7 and no augmentation.
All raw outputs were saved before loading annotation data for scoring.

| Fixed panel | Annotated objects | Matched at IoU ≥ 0.5 | Missed | Unmatched predictions |
| --- | ---: | ---: | ---: | ---: |
| Development tags | 11 | 0 | 11 | 1 |
| Outdoor tags | 33 | 12 | 21 | 1 |
| Development heads | 12 | 1 | 11 | 0 |

Outdoor tag recall is **36.36%**, with **92.31%** of the 13 tag predictions
matching publisher annotations. All 12 matches have a native tag minimum side
of at least 64 pixels, reduced to the 32–64-pixel bin at actual model input.
None of the 21 tags below 32 pixels at model input matched. Upscaling the
640×368 development images does not recover detail absent in the source.
Head accuracy on the outdoor frames was not scored because complete outdoor
head annotations do not exist. Unmatched predictions remain conservative
extras, not independently verified false physical tags: publisher completeness
is imperfect, and this result does not retroactively change that truth.

The inference loop took 1.42 seconds; the guarded operation including model
setup and provenance checks took 2.39 seconds. The separate 180-second/8-GiB
guard recorded peak Metal driver allocation of 1.164 GB and RSS of 0.831 GB.
These short-run timings do not establish streaming or combined OCR throughput.

The small, tightly cropped training set fitted well but did not supply the
scale/scene diversity needed by full-frame low-resolution views. This is a
plausible explanation, not a causal ablation. There is no basis to promote this
model to automatic ownership or relax its thresholds. The fixed result retains
all 44 tag and 12 head denominators; no extra threshold/model trial was run.
Any next data/training change needs a new protocol and independent test material,
since these 11 images are now exposed development evidence.

Artifacts under `results/2026-10-03/ear-tags/`:

- `localization-raw.json`: SHA256
  `c2f3ac1136b7009a245f990f0a115f518248385a8d434851dd7faae13acb4b1d`.
- `localization-score.json`: SHA256
  `2d0f9871ef5bd116b7f6fc7c79388b52930cff2bd86bad1e556c78c66ef3ea3a`.
- `localization-execution.json`: unchanged settings and resource evidence.
- `localization-independent-audit.json`: independently rebuilt every tag from
  the original publisher text labels and used a separate bipartite matcher;
  all 361 source bindings, 11 raw rows, complete panel counts and size bins
  reproduced exactly. SHA256
  `679bd0912750a8fc5ede0b474de6b39347fa2b91df3fda19cf0a8e8bc4d5ee02`.

The separate [public-model availability check](EAR_TAG_PUBLIC_MODELS.md) found
usable general OCR components, but did not verify a downloadable author-trained
cattle ear-tag localization/ownership model that removes this gap.

## Fixed native-tile control: no improvement

The next single control reused the same final checkpoint and all 11 now-exposed
images, with no retraining or confidence changes. Protocol
`eartag_localization_tiles_protocol.json`, SHA256
`1c01f11eb861d0e19e16d3b276ebe0b82858d4b32f8e76627791478ff87adb65`,
bound 548 files before inference. All 55 deterministic 1280-pixel tiles used
20% overlap, with edge anchoring and no annotation-centered crops. Predictions
were translated to native coordinates, then merged by public class-aware
`torchvision.ops.batched_nms` on CPU at the same 0.7 IoU. Every tile's raw and
mapped predictions are retained; there is no global 300-output cap.

The three low-resolution images passed exact original raw-box, input-shape and
post-merge parity before scoring. The old full-frame counters and pairings also
reproduced exactly. All tag and head denominators remain unchanged.

| Panel | Matched | Missed | Unmatched predictions |
| --- | ---: | ---: | ---: |
| Development tags | 0/11 | 11 | 1 |
| Outdoor tags | 11/33 | 22 | 15 |
| Development heads | 1/12 | 11 | 0 |

Outdoor performance worsened from 12 matches and 1 extra to 11 matches and 15
extras. Preserving source scale alone does not rescue the small training set;
cropping also changes context and creates partial-object predictions. This is a
failed exploratory control, not evidence against retaining original pixels for
OCR. No additional tile size, merge threshold or model was tried.

The guarded operation took 3.58 seconds, with peak Metal driver allocation
1.163 GB and RSS 0.780 GB. The guard is an in-process watcher thread with
180-second/8-GiB limits; the caller also supervised elapsed time. It is not an
external operating-system watchdog or a streaming throughput benchmark.

Results under `results/2026-10-03/ear-tags/`:

- `localization-tiles-raw.json`: SHA256
  `0ee666e3e69cf4d1bbc5593e7eca9a86ab0169d0b2e1796354da0530b367c134`.
- `localization-tiles-score.json`: SHA256
  `7c6f670e9ca0afb5424fd2d479c0776a6343091075bf7cb674ade6e996273de4`.
- `localization-tiles-execution.json`: complete timing and resource record.

Nine CPU tests cover edge/uneven tile coverage, coordinate translation,
class-aware duplicate suppression, retained extras beyond 300 and fail-closed
low-resolution parity before truth access.
