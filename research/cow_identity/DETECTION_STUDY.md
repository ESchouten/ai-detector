# Localization and tracking follow-up

The previous [video assessment](VIDEO_ASSESSMENT.md) exposed a localization problem before recognition: generic COCO weights often merge adjacent calves into one box. The independent annotation audit compared every numeric row against the publisher's original data without unpickling, verified the frame convention, and inspected development images. The boxes and timing are correct; the merged detections are real model errors.

## Protocol fixed before training

[detection_protocol.json](detection_protocol.json) records the source hashes, temporal split, candidate weights, confidence grid, training settings and intended acceptance targets. The localization training images cover seconds 0–298 at a two-second interval: 150 frames. Validation covers seconds 630–897 at a three-second interval: 90 frames. All eight calf IDs become one `cow` class; this does not train an identity classifier. The already explored query windows remain development data. Seconds 1800–2099 and 2700–2999 are reserved until a method is frozen.

Predictions are matched one-to-one to publisher boxes at IoU ≥0.5. Candidate confidence values are 0.10, 0.25, 0.40 and 0.60. Selection uses validation F1, breaking ties by higher precision and then higher confidence. The intended localization target is ≥85% recall and ≥90% precision, within one second per frame on MPS. Those are goals, not achieved claims.

The class-only adaptation uses no identity query images for training. It nevertheless sees the same pen and calf population, including the two animals withheld from identity enrollment. Success here would establish temporal adaptation on this video, not generalization to a new farm.

## Existing cattle-specific models

Two small, public, author-linked models were tested before training:

| Candidate | Size | Validation TP / FP / FN at selected confidence | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| ETH Zurich YOLOv8s | 22.5 MB | 9 / 89 / 708 at 0.10 | 9.18% | 1.26% |
| Aerial beef-cattle YOLO11s | 19.2 MB | 38 / 831 / 679 at 0.10 | 4.37% | 5.30% |

The [ETH Zurich authors](https://github.com/meiqing-wang/Cow-TrackingbyClassification) publish several cow detectors and their evaluation context. The separate adult-scene regression in this repository confirms that the small checkpoint works well on its original adult-cow domain. Its poor calf transfer is not evidence that the checkpoint is broken. The [beef-cattle model card](https://huggingface.co/Arvin26/Cattle-detection-model) describes aerial farm imagery and provides the second checkpoint. Its stored class name is `item`; the research runner explicitly maps class 0 to the documented single cattle class. Runtime label names are not guessed.

Both inference probes ran on MPS with FP16. Full confidence-grid results and model hashes are retained in the study artifacts. Neither specialized model meets the localization target out of the box. A model called “cow detector” still needs evaluation on the actual camera view.

## First bounded adaptation

The frozen 30-epoch pass keeps the backbone's first ten layers fixed and trains the remaining detector on the 150 early frames. Validation selects confidence 0.40: **483 true positives, 327 false positives and 234 misses**, or 59.63% precision and 67.36% recall. Lowering confidence to 0.10 raises recall to 80.75% but drops precision to 36.67%. The intended target is not met; changing confidence alone would hide the problem.

The selected checkpoint's SHA-256 is `42344ebbc0d8ff48166687ca6c6f2409bf276b493a77f616bd5c1c0faabe7727`. The actual SDK tracker, using this confidence and one input frame per second, gives:

| Segment | Localization precision / recall | Cow changes track ID | Track changes cow | Global track-ID F1 |
| --- | ---: | ---: | ---: | ---: |
| Development, 330–629 s | 72.80% / 73.25% | 117 | 20 | 35.14% |
| Recognition calibration, 1230–1529 s | 80.37% / 81.48% | 195 | 54 | 33.06% |

These are detection/tracking results, not named-cow recognition. The apparently reasonable box recall masks substantial track fragmentation. Processing the 300 sampled frames took 7.21 and 6.86 seconds respectively, excluding model construction. The complete prediction timelines are retained for recognition experiments, including incorrect and unmatched boxes.

## Mixed public-data adaptation

The second fixed pass, [detection_mixed_protocol.json](detection_mixed_protocol.json), unfreezes the backbone, adds 300 adult overhead training images from Cows2021's publisher training partition, and adds vertical flips and wider rotations. Ninety separate publisher validation images join the original calf validation set. Adult oriented torso boxes are converted from the publisher's top-left `xywh + radians` representation to clipped axis-aligned envelopes; the conversion was independently checked against the source XML and image. This aims for broader public-source adaptation rather than fitting only one pen. These changes were selected after development results, while final windows remain closed.

The full 40-epoch run completed in 21.7 minutes on MPS. The selected checkpoint is `151ed24e759bc83e656294b108f6df457034fc526fc3e283b9530c5a7fcb7d6d`. On the original calf-only calibration panel, the unchanged confidence grid selects 0.40: **610 true positives, 224 false positives and 107 misses**, or 73.14% precision and 85.08% recall. F1 improves from 0.633 to 0.787. The recall target is met, but the 90% precision target is not. At confidence 0.60 precision reaches 90.08%, while recall falls to 60.81%; that tradeoff is not described as meeting both targets.

The actual SDK ByteTrack timelines, still using one input frame per second, confidence 0.40 and MPS FP16, improve as follows:

| Segment | Localization precision / recall | Cow changes track ID | Track changes cow | Global track-ID F1 |
| --- | ---: | ---: | ---: | ---: |
| Development, 330–629 s | 81.12% / 82.33% | 107 | 11 | 44.42% |
| Later development, 930–1229 s | 84.79% / 90.18% | 166 | 25 | 33.78% |
| Recognition calibration, 1230–1529 s | 87.89% / 92.62% | 161 | 35 | 50.78% |

Processing took 6.56, 6.16 and 6.66 seconds respectively for 300 sampled frames. Better boxes improve anonymous track identity, but substantial fragmentation and switches remain. These timelines are supplied to the same recognition evaluator with the original early gallery; localization success alone is not named-cow recognition success. The later-development timeline was added subsequently for the active-enrollment study, keeping the detector settings fixed. Training CSV, checkpoint/library hashes, selected adult image hashes, calibration results and timeline summaries are retained in `results/2026-10-03/detection/`.

## Sampling and confidence controls

Separate tracking controls feed detections down to confidence 0.10 to ByteTrack but report only boxes ≥0.40. All are scored at the same 300 integer-second timestamps in the first development window:

| Inputs / confidence policy | Precision / recall | Cow changes track ID | Track changes cow | Global track-ID F1 |
| --- | ---: | ---: | ---: | ---: |
| 1 fps, direct 0.40 | 72.80% / 73.25% | 117 | 20 | 35.14% |
| 1 fps, stock tracker with 0.10 input | 69.84% / 72.67% | 172 | 25 | 33.37% |
| 1 fps, high/new 0.40 and low 0.10 | 72.80% / 73.25% | 117 | 20 | 35.14% |
| 5 fps, direct 0.40 | 71.59% / 75.29% | 176 | 37 | 25.95% |
| 5 fps, stock tracker with 0.10 input | 69.88% / 75.50% | 230 | 26 | 23.91% |

The fair low-confidence control preserves the baseline's new-track threshold, preventing additional weak tracks. It produces exactly the baseline's scored tracks on this panel. Stock low-confidence input and more frequent inference both worsen global track identity. Five inputs per second cost 26.64–28.15 seconds for the five-minute segment, versus 6.56–7.21 seconds at one input per second. These controls do **not** justify changing the application's confidence filtering or sampling rate. Better box localization remains the priority; no custom tracker is implemented.

A CPU-only control applies stricter non-maximum suppression to the cached calibration boxes. At confidence 0.40, moving IoU from 0.70 to 0.60 removes 90 false positives, but also loses 26 previously matched real animals: precision changes from 59.63% to 65.85%, recall from 67.36% to 63.74%, and F1 from 0.633 to 0.648. IoU 0.45 loses 51 matches. The small gain does not solve localization; counting fewer duplicate boxes alone would misrepresent the recall cost. Cached boxes have already been clipped to image borders, so these exploratory results must be checked with original SDK inference before adopting a different NMS setting. `detection_nms.py` preserves the original baseline unchanged and reports newly missed annotations explicitly.

The installed Ultralytics 8.4.80 also includes [OC-SORT and other SDK trackers](https://docs.ultralytics.com/modes/track). [OC-SORT's paper](https://arxiv.org/abs/2203.14360) proposes corrections to motion estimates after missing observations and nonlinear motion. That makes it a reasonable subsequent comparison on these turning/occluding animals, without introducing a custom tracker. The paper's results on other benchmarks do not establish performance on this cattle video.

## Residual error audit

`detection_errors.py` groups unmatched boxes into mutually exclusive geometric review hints. It checks duplicate-like overlap first (IoU ≥0.5 with a publisher box already matched to another detection), then boxes covering at least 60% of two animals, then partial/loose overlap (IoU ≥0.1), then little annotation overlap. These rules do not replace mask ground truth or visual review.

| Mixed-detector panel | Unmatched boxes | Duplicate-like | Spans multiple animals | Partial / loose | Little overlap |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 460 | 19.6% | 9.6% | 70.7% | 0.2% |
| Recognition calibration | 306 | 54.2% | 20.9% | 24.8% | 0.0% |

Visual examples confirm both detached head detections and boxes spanning several calves. At 330 s a head box lies inside a correct full-animal box. The current symmetric overlap/minimum-area quality gate rejects both, which can discard a useful complete crop because of an extra part detection. That is a candidate for a measured, containment-aware quality control, not a reason to allow ambiguous merged crops unconditionally. No production overlap rule has been changed by this study.

`detection_overlap.py` tests that hypothesis on the cached real boxes, retaining the same 64-pixel minimum side and border exclusion. The alternative divides intersection by the candidate crop's own area rather than the smaller of the two areas. It admits some complete bodies despite contained part detections, but also admits additional bad merged boxes:

| Panel / maximum overlap | Current: eligible matched known / unmatched | Own-area: eligible matched known / unmatched | Unmatched multi-animal boxes: current → own-area |
| --- | ---: | ---: | ---: |
| Development / 0.20 | 368 / 33 | 453 / 44 | 0 → 3 |
| Development / 0.50 | 913 / 212 | 1041 / 239 | 7 → 21 |
| Recognition calibration / 0.20 | 150 / 6 | 170 / 6 | 0 → 0 |
| Recognition calibration / 0.50 | 775 / 32 | 990 / 53 | 1 → 18 |

These are crop-eligibility counts, not accepted identity counts. The 0.30 condition and all unknown-cow counts are retained in the JSON reports. The alternative is not uniformly safer: the development segment exposes more ambiguous crops even at 0.20. It is therefore not promoted to the application's quality gate. Conversely, the strict existing gate excludes most known-cow observations in the crowded calibration scene; a conservative gate alone cannot create useful coverage.

## Actual-crop recognition check

The original MIEW encoder processed all 2436 development and 2526 calibration detections from the mixed model, including false boxes. The frozen early gallery still contains ten confirmed examples for each of six named cows; cows 7 and 8 remain unknown. No publisher track ID or query identity enters inference. The existing research EMA/overlap/TTL grid selects its operating point using only recognition calibration, treating every named unmatched detection as incorrect.

The best calibration-coverage condition uses EMA 0.5, no geometric overlap gate, a ten-second naming TTL, similarity 0.60 and margin 0.15:

| Panel | Correct names / all visible known animals | Wrong known / unknown named | Unmatched detections named | Conservative precision |
| --- | ---: | ---: | ---: | ---: |
| Recognition calibration | 185 / 1799 (10.28%) | 0 / 0 | 1 | 99.46% |
| Development | 203 / 1800 (11.28%) | 0 / 0 | 12 | 94.42% |

Both panels have 100% precision if unmatched detections are excluded, which would conceal the false-box risk. Neither cow 5 nor cow 6 is named. This is a research temporal policy, not the production `GalleryIdentifier` policy or a passed release criterion. Better localization and anonymous tracking did **not** produce satisfactory end-to-end naming. The full grid and exact feature/input hashes are retained in `results/2026-10-03/tracked/mixed-baseline.json`; image and feature caches remain local.

## Mask cleanup with imperfect prompts

`detection_mask_probe.py` applies the existing SAM2 tiny model to the first adapted detector's actual boxes at exposed seconds 330, 340 and 350. Visual inspection confirms that the masks often remove nearby calves and floor while preserving the target's coat. This is more realistic than supplying publisher boxes, but it remains a three-frame diagnostic, not mask accuracy or a recognition result.

The failure cases are instructive: one overlapping detector box at 330 s produces another mask of an already detected calf, and a false box retains pieces of two animals. Mask cleanup cannot recover every missed animal or make every bad box safe. The next useful comparison is recognition from masked **actual** detections; no additional segmentation training is justified by the montages alone. If later evidence supports a small segmenter, its pseudo-labels must come only from early/public training images, keeping evaluation frames out of fitting.

Seven to nine CPU mask prompts took approximately 1.0–1.2 seconds per frame while the MPS detector was training. These concurrent measurements are not a clean deployment latency benchmark. The manifest retains source-pixel hashes, detector timeline hash, SAM2 checkpoint hash and montage hashes; images remain ignored local research artifacts.

The existing SDK also exposes [SAM2VideoPredictor](https://docs.ultralytics.com/models/sam-2/#segment-video-and-track-objects), which propagates initially prompted objects with temporal mask memory. This is a plausible separate tracking control, not evidence that permanent identities survive arbitrary exits or camera changes. The [original Meta implementation](https://github.com/facebookresearch/sam2) likewise distinguishes prompted video propagation from an identity-recognition system.

Before measuring this path, the installed SDK's output contract needs explicit handling. In version 8.4.80, `SAM2VideoPredictor.inference` filters blank object masks and its inherited postprocessor assigns consecutive placeholder classes to remaining masks. Those classes are not stable object IDs when an object disappears. A research adapter must retain the original object index before this filtering. The video loader also grabs `vid_stride` frames before returning its first frame, so `vid_stride=20` does not seed on source frame zero. A verified frame sampler must align seed prompts and scoring timestamps exactly. The dynamic interactive predictor is not an interchangeable shortcut: its memory updates require new prompts, rather than the video's automatic propagation. No deployment behavior has changed based on API feasibility alone.

The subsequent bounded control is fixed in [detection_sam_protocol.json](detection_sam_protocol.json): source frame zero supplies eight exact box prompts, six manually assigned names and two anonymous objects. The SDK then propagates at two input frames per second through second 629, with no further prompts or ground-truth input. Scoring covers integer seconds 330–629 only. This is explicitly an oracle-initialized tracking experiment, not automatic enrollment or re-identification. `detection_sam_tracking.py` verifies every sampled FFV1 frame against its original decoded pixels, preserves original object slots, caches complete propagation and records observed memory and latency. A two-frame CPU technical smoke and missing-mask identity regression pass before the measured run; neither is an accuracy result.

The full-resolution MPS run was stopped on resource grounds. After 205 seconds, it had not reached its 101-frame progress message. macOS reported a **37.2 GB peak physical footprint** and a 31.3 GB footprint at sampling time. The sampled main thread was waiting for Metal command-buffer completion. That establishes an unusable resource profile for this particular 1024-pixel, FP32, eight-object configuration; it does not prove a deadlock or identify the memory-growth cause. Only the first-frame preview was retained, and no complete propagation/accuracy score exists. The compact diagnostic preserves exact source, checkpoint, sampler, runner and OS-sample hashes in `sam2-video-1024-resource-failure.json`. Smaller input sizes or other backends would be separate experiments, not corrections to this failed result.

The next inexpensive tracker control is fixed in [detection_botsort_protocol.json](detection_botsort_protocol.json): compare stock BoT-SORT with native-feature ReID disabled and enabled, keeping all other SDK settings and the mixed detector unchanged. The evaluated YOLO11 head can provide its own features; actual resolved settings and the feature hook are recorded so an unnoticed fallback to another downloaded model cannot be described as native features. Calibration precedes the subsequent development comparison. No extra identity model is trained by this control.

| Panel / tracker | Precision / recall | Cow changes track ID | Track changes cow | Global track-ID F1 |
| --- | ---: | ---: | ---: | ---: |
| Calibration / ByteTrack | 87.89% / 92.62% | 161 | 35 | 50.78% |
| Calibration / BoT-SORT | 89.42% / 94.49% | 174 | 33 | 40.08% |
| Calibration / BoT-SORT native ReID | 89.63% / 93.74% | 192 | 69 | 49.80% |
| Development / ByteTrack | 81.12% / 82.33% | 107 | 11 | 44.42% |
| Development / BoT-SORT | 83.95% / 85.67% | 119 | 12 | 52.09% |
| Development / BoT-SORT native ReID | 83.86% / 85.54% | 120 | 13 | 55.28% |

The native feature hook was active in both ReID runs, with resolved `model: auto`. Native features improve ID-F1 relative to stock BoT-SORT, but the calibration segment has more than twice as many track-to-cow switches as ByteTrack. The result is not consistently safer for maintaining a name. BoT-SORT processed the 300-frame panels in 8.76–8.88 seconds without ReID and 9.70–10.17 seconds with native ReID. All four timelines and compact reports are retained; no application tracker was changed.

A separate three-frame SAM resource control at 512 pixels completed on MPS: the initial frame took 2.63 seconds, followed by 0.247 and 0.102 seconds. Observed MPS driver allocation reached 2.00 GB and peak process RSS 819 MB. This is a technical smoke, not sustained-memory or tracking-accuracy evidence. [detection_sam_512_protocol.json](detection_sam_512_protocol.json) freezes the full 512-pixel development comparison separately, retaining exactly the original seed and scoring rules. The runner now preserves incomplete diagnostics and stops if observed MPS allocation exceeds 8 GiB or the rolling 30-frame average exceeds one second after ten startup frames. It also rejects incomplete cached timelines before calculating coverage, and a regression proves that incorrect initial names can lower naming precision while leaving anonymous ID-F1 unchanged.

The unreclaimed 512-pixel full run then stopped automatically after eight frames: MPS driver allocation reached 9.02 GB, above the frozen 8 GiB budget, although active tensor allocation was 325 MB and peak RSS 838 MB. No tracking score is calculated from those four integer-second observations. The retained `sam2-video-512-resource-failure.json` distinguishes this sustained-run failure from the successful three-frame smoke.

A bounded engineering control uses PyTorch's existing [`torch.mps.empty_cache`](https://docs.pytorch.org/docs/2.12/generated/torch.mps.empty_cache.html) only when observed driver allocation exceeds 6 GiB. It synchronizes before and after reclamation, retains all model state, and records the overhead before enforcing the same 8 GiB limit. [Driver allocation includes cached pools and MPS/MPSGraph allocations](https://docs.pytorch.org/docs/2.12/generated/torch.mps.driver_allocated_memory.html), so the earlier difference between driver and active tensor allocation is not, by itself, proof of retained video tensors or a memory leak. The installed SDK already prunes nonconditional memory frames.

This reclamation control completed a 20-frame proof. Driver allocation remained below 8 GiB; the first reclamation reduced 7.36 GB to 6.28 GB and cost 10 milliseconds. All four integer-second bounding-box outputs shared with the failed unreclaimed run were identical. That checks a small overlapping output sample, not bitwise equivalence of every mask or accuracy. The separate [detection_sam_reclaim_protocol.json](detection_sam_reclaim_protocol.json) freezes the full experiment with the same pixels, sampling, seed prompts and scoring interval. The sampled-clip cache can be reused across inference variants only after verifying the video hash, OpenCV version, timestamps, original frame indices, clip hash and every decoded pixel hash.

The full reclaimed run completed all **1259 frames in 203.83 seconds** on MPS FP32. Including per-frame decoding and reporting, that is 0.162 seconds per input frame. Thirty-three reclamations cost 33 milliseconds in total. The largest observed driver allocation before reclamation was 7.96 GB; it settled at 3.11 GB by the 25-second source timestamp. Peak process RSS was 873 MB. The retained nonconditional mask memory contained eight frames, with one initial conditional frame. These measurements establish a usable resource profile for this particular run, **not correct cow identity**:

| Seeded SAM512 result, scored 330–629 s | Measurement |
| --- | ---: |
| Correct names / all visible known cows | 1070 / 1800 (59.44%) |
| Wrong known names / unknown cows named | 132 / 16 |
| Unmatched detections bearing a name | 582 |
| Conservative named precision | 59.44% |
| Named precision excluding unmatched boxes | 87.85% |
| Box precision / recall at one-to-one IoU ≥0.5 | 64.38% / 64.38% |
| Global anonymous track-ID F1 | 54.04% |
| Cow changes track / track changes cow | 191 / 12 |

The name errors alone fail the reliability requirement, even before counting unmatched boxes. This variant is not promoted. The complete report, timing samples, cache reclamations and exact propagation hash are retained in `sam2-video-512-reclaimed.json`; the earlier resource failures remain separate records.

`detection_sam_audit.py` explains why counting nonempty object slots would be misleading. All eight slots remain nonempty at every integer second, but several slots follow the same animal. Of the 855 unmatched scored boxes, 504 (58.9%) have IoU ≥0.5 with a cow already assigned to another slot, 330 are partial/loose and 21 span multiple annotations. These are geometric audit categories, not segmentation labels.

Visual review at 33 seconds confirms that seed 1 and seed 6 both cover cow 6, leaving cow 1 unrepresented. At 246 seconds, seed 8 and seed 3 both cover cow 3. The one-to-one scorer alternates which duplicate receives a match; that alternation does not prove the physical object switched each time. Seed 1 receives no correct cow-1 matches in the scored interval. Meanwhile cows 4 and 5 retain 272 and 279 correct names out of 300, respectively. Seed 2 incorrectly names unknown cow 8 in 16 scored frames, with the first such assignment at 373 seconds. The audit retains exact review-frame hashes and per-seed outcomes.

This points to duplicate object propagation and failure to reacquire a displaced animal, rather than simply losing all outputs. It does not establish that every manually initialized video method is unsuitable: a model that explicitly makes its object masks compete is a distinct, worthwhile control. Perfect seed boxes also do not guarantee perfect initial masks. A farmer-facing system would need verified initial separation, safe rejection when identities become ambiguous, new-animal discovery and reacquisition; this experiment does not supply those behaviors.

## Cutie: a promising seeded-tracking result, still below the precision target

[Cutie, CVPR 2024](https://arxiv.org/abs/2310.12982), combines pixel features with object-level memory and attention to distinguish a target from distractors. The [official implementation](https://github.com/hkchengrex/Cutie) exposes streaming inference with an indexed initial object mask. That is a useful contrast to the duplicate SAM object slots seen above, but the paper's general video results are not cattle-identity evidence.

The frozen local control uses official `base mega` weights, upstream revision `ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a`, and checkpoint SHA-256 `9c05402ee36d3a356fb72715d263ba7e1ea06ad3bada48c1306491792da43023`. [detection_cutie_protocol.json](detection_cutie_protocol.json) fixes the 480-pixel shorter edge, two input frames per second, FP32 MPS, long-term memory and upstream `mem_every=5`. The first source frame receives existing CPU SAM1024 masks made from the eight publisher boxes; overlapping pixels belong to the first original mask. Six original object IDs receive names; two stay anonymous. No later ground truth enters propagation. Because SAM video received boxes while Cutie receives explicit masks, this is **not a pure architecture comparison**.

The original [detection_cutie.py](detection_cutie.py) run processed all 1259 frames in **173.08 seconds**, with peak observed MPS driver allocation 8.137 GB and peak process RSS 1.04 GB. The 8 GiB guard was not exceeded. The complete original runner is also retained locally at `.cache/cow-cutie/full-2fps/runner.py`, matching the recorded runner hash before later calibration extensions. [requirements-cutie.txt](requirements-cutie.txt) describes the isolated research environment, whose PyTorch version differs from the detector environment. Dependency versions, resolved SDK configuration, input hashes and checkpoint revision are included in `cutie-video-480.json`.

| Original Cutie result, scored 330–629 s | Measurement |
| --- | ---: |
| Correct names / all visible known cows | 1736 / 1800 (96.44%) |
| Wrong known names / unknown cows named | 1 / 0 |
| Unmatched detections bearing a name | 63 |
| Conservative named precision | 96.44% |
| Box precision / recall | 96.50% / 96.50% |
| Global anonymous track-ID F1 | 96.46% |
| Cow changes track / track changes cow | 2 / 2 |

[detection_cutie_audit.py](detection_cutie_audit.py) independently replays the common scorer and reproduces **every recorded metric exactly**. It records all 63 unmatched named boxes and the one incorrectly matched name, with source-pixel hashes and review overlays. The original definitions and counts are unchanged.

The residual errors often concern box extent. Seed 2 contributes 34 unmatched names; 33 are consecutive seconds 593–625, when its bounding rectangle grows to 2–5.9 times its own publisher box while still covering 81–100% of that cow. The sole wrong-name assignment occurs at 583 seconds: seed 1's expanded box overlaps cow 2 at IoU 0.611 and its intended cow 1 at 0.442. Cow 2's own predicted slot still overlaps cow 2 at 0.557 but loses the one-to-one assignment. Visual review of all 64 error panels confirms expanded boxes often include adjacent animals; three cases instead cover less than half of the intended cow's annotation.

The original run retained boxes, not full predicted masks. Its evidence therefore cannot distinguish disconnected stray mask fragments, connected leakage and physical identity drift conclusively. A separately frozen **raw versus largest 8-connected mask component** comparison is justified on calibration, retaining the unchanged scorer and both gains and losses. It must not be selected by correcting individual development-frame errors, and removing components can discard real occluded body parts. Confidence rejection, if evaluated, needs one universal rule selected only on calibration.

The subsequent continuous calibration run caches indexed masks and repeats the complete development prefix. An independent check finds **zero differing boxes over all 630 integer-second development frames**. This permits a more informative audit of matching failure geometries, although the missing original mask archive prevents a bitwise mask-equality claim. At 583 seconds, seed 1 has a 5858-pixel body component and a separate 154-pixel island on another animal; the island expands its box. At 607 seconds, however, seed 2 has a single 16438-pixel component connected by a long leakage band across foreground animals, plus only four separate pixels. Largest-component cleanup cannot remove that connected error. The original counts remain unchanged, and no development confidence threshold is chosen from this audit.

This is the strongest continuous tracking result so far, but its conservative precision still fails the 99% target. It also assumes eight correctly initialized objects that remain in one camera view. It does not solve automatic enrollment, new arrivals, overnight persistence, camera changes or reacquisition after departure. Further calibration and reserved evaluation are required before any application promotion.

### Longer calibration rejects the proposed confidence gate

The separately frozen [calibration protocol](detection_cutie_calibration_protocol.json) extends the same initial masks continuously through 1529 seconds, processing 3059 frames at two frames per second. Only 1230–1529 seconds select an operating point. The complete run took **490.31 seconds**, including indexed PNG caching and probability statistics, with peak observed MPS driver allocation 6.344 GB. Releasing unused Metal cache above 6 GiB remained an engineering resource control; model memory and outputs were preserved.

[detection_cutie_variants.py](detection_cutie_variants.py) validates every scored mask hash, original object slot, area and raw bounding rectangle before comparing exactly twelve frozen conditions. Largest-component cleanup uses eight-connected OpenCV SAUF labeling, choosing maximum pixel area and then the first row-major component on an area tie. The optional quality gate uses the tenth percentile of the original assigned-object probabilities, before cleanup. A failed gate removes only the name; its detection remains in localization and coverage counts. No truth label enters either transformation.

The later interval contains 1799 annotated known-cow observations and 598 unknown-cow observations. All named unmatched boxes count as errors:

| Box rule / minimum probability | Correct known coverage | Conservative named precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: |
| Raw / 0 | 86.99% | 89.74% | 27 / 0 / 152 |
| Raw / 0.50 | 86.60% | 91.65% | 27 / 0 / 115 |
| Raw / 0.70 | 72.04% | 95.15% | 11 / 0 / 55 |
| Raw / 0.80 | 45.91% | 97.75% | 5 / 0 / 14 |
| Raw / 0.90 | 9.06% | 98.79% | 0 / 0 / 2 |
| Raw / 0.95 | 0.39% | 100% | 0 / 0 / 0 |
| Largest component / 0 | 90.16% | 93.00% | 28 / 1 / 93 |
| Largest component / 0.50 | 89.88% | 95.12% | 28 / 1 / 54 |
| Largest component / 0.70 | 74.21% | 98.02% | 11 / 1 / 15 |
| Largest component / 0.80 | 46.19% | 98.34% | 5 / 1 / 8 |
| Largest component / 0.90 | 9.06% | 98.79% | 0 / 0 / 2 |
| Largest component / 0.95 | 0.39% | 100% | 0 / 0 / 0 |

**No condition passes the combined 99% precision, 60% coverage and at most 1% unknown false-naming requirement.** Component cleanup improves box extent overall, but neither cures connected leakage nor guarantees a safer identity. At probability 0.70 it names 1335 known observations correctly while making 27 errors, including one unknown cow given a name. Increasing the gate enough to meet precision leaves only seven correct names across the whole calibration panel.

The frozen tie rule selects raw boxes with probability at least 0.95 among the precision-qualified conditions. Applying that exact choice once to already exposed development, without retuning, names **one of 1800** known observations correctly (0.056% coverage). This is an unusably sparse operating point, not a successful 100%-precision system. Both `cutie-calibration-variants.json` and `cutie-selected-development.json` retain the counts, hashes and unchanged scorer provenance. The helper's `--development-output` option reproduces this selected-rule replay; it cannot select a threshold on development.

The promising first ten minutes therefore did not establish sustained reliable identity. This candidate is **not promoted**, and the reserved 1800–2099 and 2700–2999 second windows remain unopened. Further work would need a separately justified method for detecting drift and reacquiring identities, rather than lowering the quality target or presenting a shorter favorable interval alone.

### Causal audit: confident masks can absorb another cow

A subsequent CPU-only audit inspects all 27 errors from largest-component cleanup with probability at least 0.70, plus the two closest correct examples above and below that threshold for each named cow. This condition is examined to understand its failures; it does not replace the unsuccessful frozen selection. `cutie-calibration-causal-audit.json` retains the geometry, mask statistics and image hashes. No new threshold sweep is performed.

Twenty errors concern slot 6: all eleven incorrect known names refer to cow 5, and nine masks are unmatched. At 1260 seconds, slot 5 contains 7827 pixels. It shrinks to 769 pixels at 1271 seconds and 639 at 1276, and is absent by 1338. Meanwhile slot 6 covers both adjacent animals. At 1366 its connected mask visibly spans the two cows even after they start moving apart. This is a merged-object episode; removing disconnected islands cannot solve it.

The incorrect merged mask at 1276 seconds is temporally stable and visually compact: probability 0.847, previous-mask IoU 0.960, solidity 0.966 and bounding-box occupancy 0.834. Correct examples near probability 0.70 have occupancy as low as 0.28 and solidity as low as 0.64. Therefore a compactness or short-term stability requirement alone does not offer a credible separation. High segmentation confidence is not proof of a correct permanent identity.

The remaining seven errors involve three partial/tight slot-1 boxes, three slot-4 extent errors and one transient slot-3 assignment to unknown cow 7 at 1516 seconds. Adjacent source frames show both physical tracks separately before and after the latter event; the tight visible-mask rectangle overlaps another full-body annotation at the ambiguous instant. This is not convincing evidence of a lasting identity exchange, but the conservative error remains in the score. Box annotations cannot establish segmentation accuracy.

The next defensible **proposed, untested** control is relational collision quarantine. Maintain an object's recent reliable mask area and location. If a mask collapses or disappears while a neighboring slot occupies its recent region, mark both names uncertain, rather than trusting the surviving slot's increased confidence. Keep their anonymous masks so localization continues. A single frame's motion/area shock can trigger temporary rejection, but must not automatically invent a different name. Any quantitative thresholds and recovery duration must be frozen before a new bounded experiment; this audit has not selected them.

Recovery should require independent corroboration: for example, the existing frozen MIEW encoder can compare several clean post-separation crops with **human-confirmed** gallery examples. Disagreement should suppress a name, not rewrite enrollment or opportunistically swap labels. This is a veto/reacquisition hypothesis, not evidence that MIEW's poor stand-alone re-identification has been fixed. A useful experiment would report baseline, quarantine-only and quarantine-plus-verifier separately, including rejected observations, recovery delay and false reacquisitions. Calibration and final testing must remain distinct; the already inspected interval is development evidence for this proposed method.

### First relational quarantine control: no triggers

[detection_cutie_quarantine_protocol.json](detection_cutie_quarantine_protocol.json) freezes a bounded CPU control before scoring. A donor must fall below 25% of its preceding 30-frame median raw area; another object must occupy at least half of an adequate historical donor mask. The historical anchor must have probability at least 0.70 and area at least half that median, with highest probability and then newest frame breaking ties. Both original names become uncertain on a conflict. Recovery requires three consecutive restored-ownership frames; masks and boxes are never removed or reassigned.

The complete cached 0–1529 second replay produces **zero conflicts**. All measurements remain exactly equal to largest-component cleanup with probability at least 0.70:

| Exposed interval | Correct known coverage | Conservative named precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: |
| 330–629 s | 82.22% | 98.86% | 1 / 0 / 16 |
| 930–1229 s | 79.05% | 98.89% | 0 / 0 / 16 |
| 1230–1529 s | 74.21% | 98.02% | 11 / 1 / 15 |

This is a failed control, not evidence that merging is absent. Prerequisite inspection explains the miss: at 1262 seconds, slot 5 contains only 1020 pixels against its 10195.5-pixel reference median, but its highest preceding probability is 0.67. The additional anchor probability cutoff prevents considering the contaminated donor at all. A low-confidence donor can still damage a high-confidence receiver. Ranking historical anchors by quality without requiring the naming-confidence cutoff is a distinct possible control; it has not been silently substituted for this recorded failure.

[detection_cutie_quarantine.py](detection_cutie_quarantine.py) and its synthetic regressions cover disappearance without absorption, both original IDs becoming uncertain, unchanged pixels, a persistent reference despite median aging, recovery-streak reset, the strict collapse boundary, past-only anchor selection and timestamp gaps. The complete empty conflict timeline and strict metrics are retained in `cutie-quarantine.json`. This exploratory research has not changed the application's behavior or opened reserved footage.

### Second relational control: fewer merged names, but stale anchors reject correct ones

A separately frozen [second protocol](detection_cutie_quarantine_v2_protocol.json) removes only the hard probability cutoff on historical anchors. It still chooses the highest-probability adequate-area anchor from the preceding 30 seconds, with all collapse, absorption and recovery rules unchanged. This is a causal follow-up to a known prerequisite failure, not an independent validation or an unreported replacement for the first run.

The complete replay produces four conflict episodes. The relevant donor-5/receiver-6 pair is quarantined at 1250 seconds, briefly restored at 1253, quarantined again at 1262 and restored at 1378. The second episode captures the previously audited merged masks. However, two earlier conflicts involving donor 2 and receivers 5/6 last until 941 and 1042 seconds. An animal moving away from its old anchor can delay the purely geometric restoration test even when later naming is correct.

| Exposed interval | Baseline correct names | Quarantine correct names / coverage | Conservative named precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: | ---: |
| 330–629 s | 1480 / 1800 | 1480 / 1800 (82.22%) | 98.86% | 1 / 0 / 16 |
| 930–1229 s | 1419 / 1795 | 1265 / 1795 (70.47%) | 98.75% | 0 / 0 / 16 |
| 1230–1529 s | 1335 / 1799 | 1278 / 1799 (71.04%) | 99.38% | 0 / 1 / 7 |

In the later calibration panel, quarantine removes all eleven incorrect known names and eight unmatched names, at the cost of 57 correct names. Unknown false naming is 1/598 (0.17%). This exploratory panel meets the numerical 99% precision, 60% coverage and 1% unknown-false-naming gates. **It does not establish a robust passing method:** the already exposed 930-second panel loses 154 correct names without eliminating any of its sixteen errors, and both earlier panels remain below 99% conservative precision. Stale spatial anchors cause over-rejection; they do not independently establish which cow a surviving mask contains.

Masks, box localization and anonymous tracking measurements remain exactly unchanged. The complete original-slot conflict timeline for seconds 0–1529, eight trigger/recovery events, fixed protocol hash and strict scores are retained in `cutie-quarantine-v2.json`. No per-cow exceptions or further quarantine threshold sweep were used. Combining this fixed uncertainty veto with independently calibrated appearance corroboration is a separate experiment, not a claim that this control already solves identity.

### Appearance corroboration and geometric padding do not close the gap

The [appearance protocol](cutie_appearance_protocol.json) uses the unchanged MIEWid encoder and the same sixty early, human-confirmed gallery examples, ten per named cow. Query features come from each original Cutie slot's largest mask component, with the background removed. The verifier can only retain or suppress that slot's original name; it cannot relabel a slot or enroll its own predictions. Eighty fixed combinations of segmentation probability, own-name gallery similarity, separation from other names and one/three consecutive observations are selected on 1230–1529 seconds only.

The [appearance report](results/2026-10-03/detection/cutie-appearance.json) selects probability at least 0.70, own similarity at least 0.50 and a similarity advantage of 0.05, with one passing observation. It names 961/1799 known observations correctly: **53.42% coverage at 99.07% conservative precision**, below the 60% coverage target. Applying this exact choice to the two earlier panels gives 40.22% coverage at 98.77% precision and 44.57% at 99.13%. Cow 5 receives no correct names in either earlier panel. The appearance veto is not a general identity solution and does not turn uncertain segmentation into reliable recognition.

A separately frozen [temporal control](cutie_temporal_protocol.json) averages only past/current features within an uninterrupted original object slot. It compares exponential weights 1.0, 0.5 and 0.2 with the same eighty appearance conditions, resetting on a missing timestamp or slot. The highest calibration coverage satisfying precision/unknown constraints is 53.42%, 49.19% and 52.81%, respectively. Thus [temporal selection](results/2026-10-03/detection/cutie-temporal-appearance.json) retains the original single-frame condition; smoothing adds no successful operating point. No future frames or scoring-boundary resets are used.

The [fixed conjunction with quarantine](results/2026-10-03/detection/cutie-appearance-quarantine.json) also fails to add useful evidence. Calibration selects the weakest appearance requirements, and all three panels' decisions equal quarantine alone. Its calibration `meets_all_gates` flag is therefore not evidence of success on development or a separate gain from MIEWid.

Finally, the [geometric control](cutie_geometry_protocol.json) expands every largest-component rectangle uniformly by factors 1.0, 1.1 or 1.2, keeping quarantine, names, masks, annotations and matching unchanged. This tests whether tight mask rectangles merely omit extremities. Calibration results are:

| Box scale | Correct known coverage | Conservative named precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: |
| 1.0 | 71.04% | 99.38% | 0 / 1 / 7 |
| 1.1 | 70.98% | 99.30% | 0 / 1 / 8 |
| 1.2 | 68.54% | 95.88% | 0 / 5 / 48 |

The [recorded selection](results/2026-10-03/detection/cutie-geometry.json) keeps unexpanded boxes. Padding increases confusion with adjacent animals instead of fixing the remaining failures. These controls support investigating the upstream propagation itself—for example, a separately frozen higher input cadence—rather than accumulating more downstream thresholds. They do not justify changing the application's production identity behavior.

### Five input frames per second improves continuity, but still misses the precision target

The [separate cadence protocol](cutie_cadence_protocol.json) fixes continuous processing of source seconds 0–1529 at five frames per second. It keeps official Cutie FP32 at a 480-pixel shortest edge, the same first-frame manual masks and SDK memory settings. Scoring and the unchanged quarantine-v2 history remain at one frame per second. All 7,646 source frames are decoded at exact source indices and preserved losslessly; no later prompt or identity correction is introduced.

The [completed result](results/2026-10-03/detection/cutie-cadence-5fps.json) retains both the fixed largest-component/probability-0.70 condition and its fixed quarantine conjunction. There is no threshold selection:

| Exposed panel | Correct names with quarantine / known observations | Coverage | Conservative precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: | ---: |
| 330–629 s | 1556 / 1800 | 86.44% | 98.668% | 0 / 0 / 21 |
| 930–1229 s | 1434 / 1795 | 79.89% | 98.625% | 4 / 0 / 16 |
| 1230–1529 s | 1560 / 1799 | 86.71% | 98.547% | 0 / 0 / 23 |

In the middle panel, quarantine changes 1530 correct names, ten wrong known names and 34 unmatched names into the second table row. One donor-6/receiver-3 conflict from second 1000 to 1096 removes six wrong and eighteen unmatched names, while suppressing 96 correct names. The other panels have identical base/quarantine decisions. No anonymous animal is named, but **every panel still fails the 99% conservative precision requirement**. Higher coverage alone does not justify promotion.

The full run took 1127.79 seconds. Mean per-frame processing was 146 ms, with p95 220 ms and p99 247 ms; 1100/7646 frames (14.4%) exceeded the 200 ms input interval. Observed peak Metal driver allocation was 6.27 GB and peak resident memory 0.90 GB, without a resource stop. Average throughput therefore fits this sampled stream on this Mac, but individual deadlines and concurrent detector performance are not established. This is a materially costlier condition than two-frame-per-second propagation.

Keeping the SDK's `mem_every=5` unchanged means memory writes occur once per second here, versus once per 2.5 seconds in the earlier run. Consequently, this is a fixed-SDK cadence comparison, not proof that input frequency alone caused the difference. [detection_cutie_cadence.py](detection_cutie_cadence.py) verifies complete timestamp coverage and seed ordering and reuses the original strict one-to-one evaluator. The reserved intervals remain unopened.

### Can actual proposals initialize the first frame?

The manually seeded controls above supplied publisher boxes, so their initial coverage does not measure a farmer's actual setup flow. A [separate first-frame diagnostic](detection_initialization_protocol.json) freezes the mixed cow detector at confidence 0.40, image size 640 and CPU FP32. [detection_initialization.py](detection_initialization.py) predicts and caches every proposal before loading the frame's truth annotations. It decodes only source frame zero and creates no SAM masks.

The [result](results/2026-10-03/detection/cutie-actual-initialization.json) contains twelve proposals: eight one-to-one IoU ≥0.5 matches and four extra partial/duplicate proposals concentrated around cows 2 and 7. All eight visible cows, including all six known animals, have a matching proposal. Seed recall is therefore 100%, proposal precision 66.67%, and the **ideal correctly confirmed known-cow coverage ceiling is 100%**. A local contact sheet retains every actual proposal alongside the separately drawn annotations; no box was replaced or selected before prediction.

This clears a necessary geometric feasibility check for that frame, but is deliberately optimistic: **source frame zero was included in this detector's early training data**. It is not held-out accuracy, and an ideal farmer who rejects all duplicate proposals is not a measured onboarding workflow. Overlapping matched boxes can still produce contaminated SAM seeds; that requires a separate test. No continuous tracker or reserved frame was evaluated here. Source/model/pixel hashes, actual CPU backend and complete proposal coordinates remain in the compact report.

### Masks from reviewed actual boxes differ from the annotation-prompt seeds

The subsequent [initial-mask protocol](detection_initial_masks_protocol.json) fixes one visually complete proposal for each visible animal before SAM inference. Original cow-slot order 1–8 uses proposal indices `[4, 7, 2, 3, 1, 0, 5, 10]`; slots 7/8 remain anonymous. Review rejects duplicate proposals 6/8/9/11, without changing any retained box coordinate. The simulated confirmation uses source context and publisher animal numbers as names, not model identity predictions. The twelve-proposal report and all review reasons remain available.

[detection_initial_masks.py](detection_initial_masks.py) then applies the same SAM2.1 tiny checkpoint, image size 1024 and CPU FP32 as the original initialization. All eight resulting masks remain present when converted to original indexed slots. They have no overlapping pixels, compared with 174 overlapping pixels in the original binary masks; the same first-slot-priority overlap policy is retained. The [comparison report](results/2026-10-03/detection/cutie-actual-seed-masks.json) records these mask agreements:

| Original slot | Binary mask IoU with original initialization |
| --- | ---: |
| 1 | 0.771 |
| 2 | 0.975 |
| 3 | 0.992 |
| 4 | 0.974 |
| 5 | 0.988 |
| 6 | 0.971 |
| 7, anonymous | 0.939 |
| 8, anonymous | 0.841 |

These are **agreements between two model outputs, not segmentation-accuracy measurements**. Visual comparison shows meaningful extent changes for slots 1 and 8; similar initial masks also do not guarantee equal long-term propagation. The actual-proposal masks, their independent manifest and comparison contact sheet are retained separately from the original masks. This one-frame CPU operation took 1.03 seconds. It ran no Cutie tracking, opened no later footage and does not establish farmer effort or new-camera generalization.

### Stateless SAM refinement does not improve the sparse calibration control

A [fixed thirty-frame control](detection_refinement_protocol.json) selects seconds 1230, 1240, …, 1520 before inference. Each present Cutie slot supplies its largest-component rectangle as a prompt to the same CPU FP32 SAM2.1 tiny model at 1024 pixels. Each returned binary mask supplies a new full bounding rectangle, preserving its original slot. Missing slots remain missing; anonymous slots are included. Independent masks can overlap, and no additional cleanup or pixel arbitration hides resulting duplicates.

The name decision remains original Cutie probability ≥0.70 plus the existing quarantine-v2 decision. SAM cannot rescue a rejected name, assign a different identity or change tracking history. [detection_refinement.py](detection_refinement.py) caches all thirty predictions before loading labels and calls the unchanged strict scorer at each selected timestamp. This is sparse geometry evaluation, not a continuous identity or tracking score.

| Same thirty calibration frames | Original LCC boxes | SAM-refined boxes |
| --- | ---: | ---: |
| Correct names / visible known cows | 132 / 180 | 131 / 180 |
| Correct known coverage | 73.33% | 72.78% |
| Conservative named precision | 99.25% | 98.50% |
| Wrong known / unknown named / unmatched named | 0 / 0 / 1 | 0 / 0 / 2 |
| Matched boxes / visible annotations | 225 / 240 | 224 / 240 |

The [complete report](results/2026-10-03/detection/cutie-sam-refinement.json) records only one strict-count change: at 1490 seconds, the refined slot-3 rectangle becomes too tight to match its intended cow at IoU ≥0.5. The existing unmatched slot-1 box at 1230 seconds remains unmatched. Side-by-side source overlays and masks are cached for every chosen timestamp; all original errors remain counted.

SAM inference took 20.63 seconds on CPU, approximately 0.69 seconds per selected frame. Since this fixed control adds cost and loses a correct match, it does not justify integrating per-frame refinement or making an MPS performance claim. It also does not rule out every possible refinement architecture: this result concerns the specified stateless box-prompt method, not learned corrections or feedback into video memory. No threshold search, extra prompts, later frames or reserved footage were used.

### Independent detector corroboration: a promising fixed candidate, not the selected result

The [next frozen control](detection_corroboration_protocol.json) keeps the original Cutie largest-component boxes, identities and quarantine decisions. A name receives one extra geometry check: its original box must have IoU at least 0.50 or 0.70 with a same-frame box from the independent mixed YOLO detector. No labels enter this check and no box is replaced. One detector box can corroborate multiple slots; duplicate errors remain visible to the strict one-to-one evaluator.

All 900 required cached detector timestamps exist. They contain the existing **ByteTrack-filtered** mixed-YOLO predictions at confidence 0.40 and one frame per second, not raw untracked detections. Before scoring, [detection_corroboration.py](detection_corroboration.py) verifies model/file hashes and every predicted crop's stored pixel hash against its exact cached source frame. It generates no new inference and does not interpolate missing boxes. No sampled frame has zero detector boxes, although particular tracked cows can lack sufficient cross-model overlap.

| Exposed panel / extra IoU requirement | Correct names / known observations | Coverage | Conservative precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: | ---: |
| 1230–1529 / none | 1278 / 1799 | 71.04% | 99.378% | 0 / 1 / 7 |
| 1230–1529 / 0.50 | 1235 / 1799 | 68.65% | 99.356% | 0 / 1 / 7 |
| 1230–1529 / 0.70 | 627 / 1799 | 34.85% | 99.524% | 0 / 0 / 3 |
| 330–629 / none | 1480 / 1800 | 82.22% | 98.864% | 1 / 0 / 16 |
| 330–629 / 0.50 | 1207 / 1800 | 67.06% | 99.260% | 0 / 0 / 9 |
| 330–629 / 0.70 | 589 / 1800 | 32.72% | 100% | 0 / 0 / 0 |
| 930–1229 / none | 1265 / 1795 | 70.47% | 98.751% | 0 / 0 / 16 |
| 930–1229 / 0.50 | 1137 / 1795 | 63.34% | 99.128% | 0 / 0 / 10 |
| 930–1229 / 0.70 | 468 / 1795 | 26.07% | 99.363% | 0 / 0 / 3 |

**The predeclared calibration-only selection keeps the baseline with no extra veto.** It has higher calibration coverage and slightly higher precision than the 0.50 condition; its earlier replays therefore still fail the precision target. The [retained report](results/2026-10-03/detection/cutie-detector-corroboration.json) preserves this unsuccessful selected result. The selection rule was not retroactively changed to prefer an attractive development result.

Separately, the fixed 0.50 candidate reaches the numerical 99% precision, 60% known coverage and at most 1% unknown-false-naming gates on all three exposed panels. It rejects 43, 281 and 134 previously permitted names on calibration, early development and later development, respectively. At 0.70, geometric disagreement rejects too many correct names. This is useful direction for a **new fully frozen method**, but these panels have informed many earlier experiments and are not independent confirmation. Manual initial seeds, the scene-adapted detector and the untouched reserved tests remain material limitations.

The earlier cached detector runs took approximately 20.5–22.2 ms per input frame including their video/tracker work on MPS. This is evidence of a cheaper component than the CPU SAM refinement above, not measured concurrent Cutie-plus-detector throughput or a guarantee on another machine. A combined implementation would need its own resource and latency check before deployment.

### Actual initialization and stateless corroboration do not reproduce the passing development candidate

All three panels above were already exposed method development. The subsequent [explicit freeze](detection_actual_seed_protocol.json) selects the predefined 0.50 corroboration candidate using all three panels, while preserving the unsuccessful earlier calibration-only selector. This is a new development decision, not a reinterpretation of that earlier selection or a held-out result.

The new control changes **two** pipeline inputs before inference: it initializes from the independently reviewed actual detector proposals/SAM masks, and it replaces panel-reset ByteTrack-filtered corroboration with stateless raw `YOLO.predict` boxes at every integer second. The mixed detector, confidence 0.40, image size 640 and FP16 MPS precision remain fixed. Cutie still propagates continuously at two frames per second with FP32 MPS and its existing memory settings. The largest component, original probability ≥0.70, frozen quarantine-v2 rules and same-frame IoU ≥0.50 name check are unchanged. Quarantine is recomputed from the new masks, not copied from a previous run.

[detection_corroborator.py](detection_corroborator.py) verifies every processed frame's pixel hash and retains all 1530 stateless results before scoring. The independently reviewed [combined scorer](detection_actual_score.py) checks complete timestamps, source/seed/model bindings and actual inference precision. It reconstructs uncertainty before reading annotations and uses the same strict one-to-one naming metric. The [result](results/2026-10-03/detection/cutie-actual-seed-pipeline.json) is:

| Exposed panel | Correct names / known observations | Coverage | Conservative precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: | ---: |
| 330–629 s | 1265 / 1800 | 70.28% | 98.905% | 0 / 0 / 14 |
| 930–1229 s | 982 / 1795 | 54.71% | 99.092% | 0 / 0 / 9 |
| 1230–1529 s | 1240 / 1799 | 68.93% | 99.518% | 0 / 0 / 6 |

**The frozen actual pipeline fails the all-panel target:** early precision falls below 99%, and middle-panel coverage falls below 60%. Zero wrong names among matched boxes does not remove the 29 named unmatched errors. No thresholds were changed after observing this outcome. Fresh quarantine now suppresses the donor-2/receiver-6 pair until second 1035 and donor-2/receiver-1 until 1112. The sensitivity of these prolonged episodes to small initialization changes requires causal review, not an assumption that the previous coverage result transfers.

The complete 3059-frame Cutie run took 450.79 seconds, with mean frame processing 146 ms, p95 197 ms and p99 214 ms; no frame exceeded its 500 ms sampling interval. Observed peak driver allocation was 6.41 GB and peak resident memory 1.22 GB. The separate 1530-frame raw detector pass took 24.84 seconds. These are separately measured component runs, not a concurrent application benchmark; their recorded environments also differ (Cutie PyTorch 2.11.0, detector PyTorch 2.12.1). Exact dependencies and actual backends are retained in the report.

This entire Cutie family concerns **continuous, within-camera tracking after a single initial confirmation**. It processes all intermediate frames and does not reset at scoring-window boundaries. The original [iteration protocol](ITERATION_PROTOCOL.md) describes a different, disconnected-window re-identification experiment; that frozen baseline remains unchanged. Any later reserved evaluation of continuous tracking requires its own explicit addendum and frozen full sequence, with no new prompts, truth access or hidden state reset between score windows. Neither new arrivals nor recognition after leaving and returning has been demonstrated here. The reserved intervals remain closed.

### Causal replay separates initialization sensitivity from stale quarantine

The [fixed audit](detection_actual_audit_protocol.json) changes no confidence, overlap or matching threshold. It compares the actual-seed pipeline without quarantine and the original manual-seed pipeline with the new stateless corroborator. All strict metrics for the actual-seed baseline reproduce exactly in the [audit report](results/2026-10-03/detection/cutie-actual-seed-audit.json).

With original manual seeds and raw corroboration, the three panels still pass the numerical development gates: coverage/precision are 69.39%/99.127%, 66.13%/99.082% and 69.37%/99.522%. Replacing panel-reset tracking outputs with raw detections therefore does not explain the main regression. The changed initial masks and their later history matter.

Removing quarantine from the actual-seed pipeline restores 333 correct names in the middle panel, reaching 1315/1795 (73.26%) coverage at 99.320% precision, without adding a named error there. But the same removal in calibration adds twelve wrong known names and three unmatched names, producing 1297/1799 (72.10%) coverage at only 98.407% precision. Quarantine is useful for genuine ownership confusion and simultaneously over-rejects long after some animals have moved away from old anchor pixels. Removing it globally is not a solution.

All 29 residual named errors in the actual-seed baseline have source overlays. Fifteen concern slot 1, six slot 3, three each slots 4/6, and two slot 5. Most rectangles show partial-body or loose extents near the strict 0.5-IoU boundary. At 449 seconds, the slot-1 rectangle overlaps its own annotation at 0.564 but loses the global one-to-one assignment to a competing box. At 1093 seconds, slot 6 is named although that cow has no publisher annotation in the frame; the rectangle spans a crowded region. These remain errors under the unchanged evaluator, without favorable relabeling after predictions. A rendering-only missing-annotation bug required a second implementation freeze; the three conditions and scoring rules were unchanged, and final metrics are saved before image rendering.

### Reciprocal geometry checks help precision; averaging boxes does not solve coverage

The separate [box consensus report](results/2026-10-03/detection/cutie-box-consensus.json) requires Cutie and the raw detector to select each other as their highest-IoU partner at the same fixed 0.50 minimum. Each independent proposal can then confirm at most one original slot. It also tests an equal coordinate mean of each reciprocal pair. Original names and masks never change, and quarantine remains unchanged.

| Fixed actual-seed condition | 330–629 coverage / precision | 930–1229 coverage / precision | 1230–1529 coverage / precision |
| --- | ---: | ---: | ---: |
| Reciprocal partner, original box | 68.89% / 99.200% | 53.54% / 99.277% | 68.15% / 99.513% |
| Reciprocal partner, mean coordinates | 68.83% / 99.120% | 53.70% / 99.587% | 68.26% / 99.675% |

Reciprocal confirmation reduces the early panel's named unmatched count from fourteen to ten and brings all panels' precision above 99%; middle coverage still fails. Coordinate averaging adds a wrong known name in the early panel, with only tiny coverage changes elsewhere. There is no evidence here to justify integrating that extra geometry modification.

The [weighted boxes fusion paper](https://arxiv.org/abs/1910.13302) motivated testing cross-model geometry, but this equal-mean control is **not the paper's confidence-weighted fusion algorithm**. Cutie mask probabilities and detector confidence scores are not assumed comparable. No weighted-fusion performance claim or threshold search is made.

### Recovering from current observations restores coverage without removing real quarantine

The [single recovery control](detection_quarantine_recovery_protocol.json) keeps the existing conflict discovery and its saved reference area. It changes only restoration: for three consecutive one-second observations, both original slots must have probability ≥0.70 and **different reciprocal** raw-detector partners at IoU ≥0.50, while the donor's original-mask area is at least half its saved reference area. The animals no longer have to return to historical pixel positions. Failed evidence resets the streak; no identity, mask or rectangle is reassigned.

This is a testable geometry hypothesis, not proof that a name survived an occlusion. [CorroboratedRecovery](detection_quarantine_recovery.py) exposes the same causal incremental interface for later integration. Synthetic tests cover movement away from old anchors, shared-proposal ambiguity, interrupted confidence streaks, the donor-area boundary and unchanged pixels. Restoration still runs before the unchanged discovery step; altered conflict history can affect later events and is retained in full.

The [replay](results/2026-10-03/detection/cutie-quarantine-recovery.json) exactly reproduces the previous baseline. It releases pair 2/1 at second 772 instead of 1112 and pair 2/6 at 776 instead of 1035. The genuine later pair 5/6 remains blocked until 1378. Middle-panel coverage rises from 54.71% to 73.26%, restoring all 333 suppressed correct names without adding an error. Early/calibration decisions are identical. No additional trigger episode appears in this replay, and no rule was tuned after these counts.

A [separately frozen conjunction](detection_recovery_consensus_protocol.json) then adds the already tested reciprocal naming requirement to this recovered state. It keeps original boxes, probability 0.70 and IoU 0.50 unchanged, with no coordinate averaging or further selection. Its [result](results/2026-10-03/detection/cutie-recovery-consensus.json) is:

| Actual-seed, two-frame-per-second pipeline | Correct names / known observations | Coverage | Conservative precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: | ---: |
| 330–629 s | 1240 / 1800 | 68.89% | 99.200% | 0 / 0 / 10 |
| 930–1229 s | 1293 / 1795 | 72.03% | 99.462% | 0 / 0 / 7 |
| 1230–1529 s | 1226 / 1799 | 68.15% | 99.513% | 0 / 0 / 6 |

**This candidate meets the numerical targets on all three exposed development panels.** All 23 named unmatched errors remain counted, and unknown false naming is 0/600, 0/598 and 0/598. The preceding recovered/maximum-IoU baseline reproduces exactly. These correlated frames have informed many experiments, so this is method selection—not an independent accuracy estimate or successful reserved test. A combined application-runtime run and a separately frozen continuous reserved evaluation are still required.

For comparison, the [cached five-frame-per-second reciprocal control](results/2026-10-03/detection/cutie-cadence-consensus.json), with original manual seeds and original quarantine, also meets the development gates: coverage/precision are 71.33%/99.227%, 74.04%/99.179% and 82.82%/99.069%. It includes four wrong known names in the middle panel and has not tested actual initialization. The simpler two-frame-per-second candidate therefore warrants the next combined-runtime assessment before adding the denser processing cost. Neither result demonstrates new arrivals, re-identification after leaving the view or unattended restart recovery.

### The combined application runtime reproduces the selected decisions

The [full combined run](results/2026-10-03/detection/cutie-streaming-development.json)
subsequently processed all 3059 development inputs with application PyTorch
2.12.1, Cutie FP32 and YOLO FP16 in one MPS process. At all 1530 integer-second
timestamps, its original masks, detector geometry, largest-component geometry,
names and quarantine states matched the separate-process reference exactly.
All three panels therefore retain the counts above. The pooled result is
3759 correct names over 5394 visible known observations (69.69% coverage),
99.392% conservative precision, no wrong known names, no unknown animal named,
and 23 named unmatched boxes. Pooling does not create independent observations.

The complete run took 482.54 seconds, including initialization and report
writes. Processing averaged 154.8 ms per input, with p95 222.4 ms and p99
237.8 ms; two of 3059 inputs exceeded the 500 ms interval. The first-frame
excluded p95/p99 were 222.4/237.6 ms. Peak observed driver allocation was
7.00 GiB before cache reclamation and 6.00 GiB afterward; peak resident memory
was 1.695 GiB. Observed working/long-term memory maxima were 10800/9984 tokens.
These are measured maxima, not a claim that a sampled compaction target is a
hard maximum. Decode, hashing, synchronized inference, decisions and mask
caching are included in input timings. This measures one camera on this Mac,
not concurrent farm deployment capacity.

[Thirty focused tests](results/2026-10-03/detection/cutie-streaming-tests.json)
and the complete 146-test research suite passed before selecting the next
experiment. The [reserved selection](detection_reserved_selection.json) fixes
the same method before additional pixels. Its continuous seeded-tracking scope
is explicitly different from disconnected-window recognition in the original
iteration protocol; the original protocol is preserved. This successful
development replay does not itself establish reserved accuracy, new-animal
entry, re-entry or name recovery after an application restart.

### The frozen continuous reserved evaluation fails its late precision target

The complete combined application runtime then processed 5999 inputs through
second 2999 without changing the selected method. The [immutable reserved
report](results/2026-10-03/detection/cutie-streaming-reserved.json) gives:

| Reserved panel | Correct / known | Coverage | Conservative precision | Wrong known / unknown named / unmatched named | All gates |
| --- | ---: | ---: | ---: | ---: | --- |
| 1800–2099 s | 1123 / 1799 | 62.42% | 99.293% | 0 / 0 / 8 | Pass |
| 2700–2999 s | 1303 / 1781 | 73.16% | 97.970% | 0 / 0 / 27 | Fail |
| Pooled | 2426 / 3580 | 67.77% | 98.578% | 0 / 0 / 35 | Fail |

These are correlated observations, not independent-animal confidence intervals.
The strict 99% precision requirement is not met; zero wrong names among matched
boxes does not remove the 35 unmatched named errors. No threshold or label was
changed. All 3059 shared source frames and 1530 integer-second outputs reproduce
the development prefix exactly, including masks, names and conflict states.

The 978.47-second run averages 158.3 ms per input, with p95/p99 226.3/251.3 ms.
Three of 5999 inputs exceed their 500 ms interval. Peak driver allocation before
and after reclamation is 6.684/5.999 GiB; peak RSS 1.184 GiB. Working/long-term
memory maxima are 10800/9984 tokens. Resource completion is not an accuracy pass.

A read-only audit rendered all 35 errors with source pixels, original masks,
paired raw YOLO proposals and unchanged publisher boxes. Thirty-three have an
own annotation with IoU 0.288–0.498; none is a duplicate-assignment loss. Twenty-nine
mask rectangles are smaller than the own publisher extent, and the paired raw
YOLO rectangle reaches own IoU .5 in 29 cases. Six masks have tiny disconnected
pieces, retaining at least 97.9% of area. At 2770 and 2790 an animal is visible in
the named cow-4 region but the publisher has no cow-4 box; both remain errors.
This suggests a further output-geometry control, not a reason to silently change
labels or the metric. [RESERVED_RESULT.md](RESERVED_RESULT.md) records exact
provenance, runtime, per-error review and reproduction caveats.

Both reserved panels are now **exposed**. Seconds **3000 onward remain closed**.
Historical protocol documents and the failed strict report remain byte-identical;
a later control is development on exposed data and cannot retroactively turn
this frozen evaluation into a pass.

### Returning all detector boxes makes the exposed-data result worse

The single [output-geometry control](detection_output_geometry_protocol.json)
keeps every recorded name, gate and reciprocal pairing fixed, but outputs the
actual same-frame raw detector proposals. Only a unique originally named partner
receives its existing identity; every other proposal stays unnamed, without
asserting a persistent track. Coordinates and confidence remain exactly those
of the detector. No proposal is discarded because it is inconvenient for the
metric, and no operating point is searched.

The [CPU replay](results/2026-10-03/detection/cutie-output-geometry.json) first
reproduces every original baseline naming count and confusion on all five
**exposed** panels. It then gives:

| Exposed panel | Correct / known | Coverage | Conservative precision | Wrong known / unknown named / unmatched named | Proposals / matched / missed / unmatched |
| --- | ---: | ---: | ---: | ---: | ---: |
| 330–629 s | 1196 / 1800 | 66.44% | 95.680% | 3 / 0 / 51 | 2640 / 2069 / 331 / 571 |
| 930–1229 s | 1259 / 1795 | 70.14% | 96.846% | 2 / 2 / 37 | 2747 / 2230 / 163 / 517 |
| 1230–1529 s | 1195 / 1799 | 66.43% | 96.997% | 1 / 4 / 32 | 2722 / 2283 / 114 / 439 |
| 1800–2099 s | 1080 / 1799 | 60.03% | 95.491% | 0 / 0 / 51 | 2387 / 1880 / 510 / 507 |
| 2700–2999 s | 1285 / 1781 | 72.15% | 96.617% | 0 / 1 / 44 | 2214 / 1950 / 343 / 264 |

**Every panel fails precision.** The number of emitted names is identical to its
baseline, but some now cover the wrong animal or lose their one-to-one truth
assignment. The detector has more false/duplicate geometry and fewer matched
animals overall. Its favorable boxes among the selected 35 original errors do
not represent its behavior on the entire sequence. Four synthetic tests include
an added unnamed duplicate stealing a truth match, ensuring that such errors
cannot disappear through filtering. Anonymous stateless proposals deliberately
have no invented track, so their track-switch counts are not a continuity
comparison with Cutie's original slots.

This negative control is not promoted. The original reserved failure remains
immutable, and seconds 3000 through the end stay closed.

### Separating extra proposals from worse geometry does not rescue a union rule

A [global diagnosis](results/2026-10-03/detection/cutie-output-geometry-diagnosis.json)
examines all 6243 emitted names, not just the original selected errors. Raw output
loses 215 previously correct names: 133 paired boxes now fall below own-cow
IoU .5; another 82 have valid own-cow overlap but lose the global assignment.
In 81 of those cases an additional unpaired raw proposal takes the own-cow match.
The remaining case (second 1467, slot 3) is instead assigned to unknown cow 7,
while cow 3 remains unmatched. Raw output fixes 45 original unmatched names but
creates 202 unmatched, six wrong-known and seven unknown-animal names. Its
own-cow IoU decreases in 4261 of the 6243 named observations.

This motivated one separately [frozen union control](detection_union_geometry_protocol.json):
retain the original collection of slots, names and confidence; for every reciprocal
pair, named or unnamed, return the rectangle containing both the original mask
box and the current raw detector box. Unpaired slots remain unchanged. No boxes
are added or removed, and no policy or threshold changes. The union cannot cut
away an existing extent, but it can include background or a neighboring animal.
The [single CPU comparison](results/2026-10-03/detection/cutie-union-geometry.json)
reproduces the baseline exactly and preserves all emitted-name and box counts:

| Exposed panel | Correct / known | Coverage | Conservative precision | Wrong known / unknown named / unmatched named | Proposals / matched / missed / unmatched |
| --- | ---: | ---: | ---: | ---: | ---: |
| 330–629 s | 1235 / 1800 | 68.61% | 98.800% | 1 / 0 / 14 | 2400 / 2295 / 105 / 105 |
| 930–1229 s | 1280 / 1795 | 71.31% | 98.462% | 1 / 0 / 19 | 2397 / 2296 / 97 / 101 |
| 1230–1529 s | 1217 / 1799 | 67.65% | 98.782% | 0 / 0 / 15 | 2344 / 2189 / 208 / 155 |
| 1800–2099 s | 1095 / 1799 | 60.87% | 96.817% | 0 / 0 / 36 | 2400 / 2246 / 144 / 154 |
| 2700–2999 s | 1288 / 1781 | 72.32% | 96.842% | 0 / 0 / 42 | 2398 / 2143 / 150 / 255 |

**All five precision gates fail again.** Avoiding additional proposals limits the
damage compared with all-raw output, but enlarging paired rectangles is still
worse than the unchanged mask baseline overall. This control is also rejected;
there is no further geometry sweep. Both new controls are exposed-data research
and leave the original reserved failure intact. Seconds 3000 onward remain closed.

### Physical review questions annotation extent before another model change

The [clean-source physical review](results/2026-10-03/detection/cutie-reserved-physical-review.json)
then inspected every one of the 35 selected failures without an opaque mask
covering the animal. Twenty-five masks appear to retain most visible anatomy
while the publisher rectangle is loose; five publisher extents appear partial
or shifted; three occluded cases remain ambiguous; two own annotations are
missing. These qualitative categories are not replacement ground truth or proof
that the biological identity is correct. The untouched strict result still fails.

Particularly, isolated calves at 2877 and 2895 seconds have coherent visible
masks despite low box IoU. The [publisher describes detector-assisted video
labels](https://arxiv.org/html/2503.13777v2), manual tracking corrections, missing
boxes and detector bias. Consequently a tight relative rectangle alone is not
adequate causal evidence for another segmentation network. A separate uniform,
independently labelled clean-frame diagnostic will examine extent quality across
both successful and failing examples before further algorithm changes. No new
held-out video has been opened and no threshold changed.

## Tools and reproducibility

- `detection_assessment.py prepare` extracts only the fixed training/validation intervals into ordinary Ultralytics YOLO data. Images and checkpoints stay in ignored local storage.
- `detection_assessment.py evaluate` caches predictions by model hash, decoded image hashes, inference settings and dependency versions. Confidence-grid replay reuses these predictions.
- `detection_assessment.py train` delegates training to Ultralytics, checks that prepared data matches the frozen protocol, preserves previous runs and records the selected checkpoint hash. This is research training, not an automatic application behavior.
- `detection_tracking.py` compares SDK ByteTrack and BoT-SORT at one or five input frames per second. Both are scored at identical one-second timestamps. It retains actual predicted crops' bounds, track IDs and publisher matches for the separate recognition evaluator. The SDK constructs trackers with its usual 30 fps setting; the report records this instead of implying tracker timeouts are expressed in wall-clock seconds.

The tracking runner currently accepts only development/recognition-calibration starts 330, 930 and 1230. The localization runner likewise excludes the final/reserve splits from its CLI, keeping reserved windows closed until a final method is recorded. Besides localization counts and track switches, tracking reports a global one-to-one track/cow assignment score: fragmentation is penalized even with perfect boxes. These are anonymous tracking measurements, not permanent cow identity accuracy.

The numeric annotation reader accepts the independently checked safe NPZ. The dataset provenance and license are recorded in the annotation audit and video assessment. No raw video, identifiable farm footage or automatically generated identity labels are published by these tools.

The recorded seed fixes the requested training setup, but does not promise bit-for-bit retraining: MPS operations and the SDK's RAM image cache can be nondeterministic. Checkpoint hashes identify the actual evaluated weights. Prediction caches avoid rerunning inference when only the scoring calculation changes.
