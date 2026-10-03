# Production-policy video assessment, 3 October 2026

**The initial cow identity preset assigned no names in this dense calf video. A stronger detector found more animals, but still assigned no names in either five-minute query segment. This is a working gallery-building prototype, not useful unattended identification in this setting yet.**

The test uses the application's actual `GalleryIdentifier`, MIEWid encoder, geometry gates and temporal agreement. It does not substitute the more favorable pooled-photo scoring from [the image benchmark](BENCHMARK.md). Neither identity thresholds nor the gallery were changed after seeing results.

## Fixed protocol

- Public [8-calves dataset](https://huggingface.co/datasets/tonyFang04/8-calves), video `pmfeed_4_3_16.mp4`, 800×600 at 20 fps. No private farm footage.
- Enroll calves 1–6 using publisher boxes at exactly 0, 10 and 20 seconds: three examples per calf. Calves 7–8 remain unknown. The examples were not selected for recognition quality or altered after scoring.
- First query: seconds 330–629, one frame each second. At least 310 seconds separate the final enrollment example from the first query.
- After examining that segment, freeze the alternative detector and run seconds 930–1229, leaving a five-minute gap. This is a sequential development follow-up within the same video, **not an independent farm test**.
- Keep production defaults: cosine similarity ≥0.65, margin ≥0.10 over a different cow, three qualifying tracked observations, one-second identity sampling, minimum crop dimension 64, maximum overlap 0.20. Do not weaken rejection to increase coverage.
- Detection runs on MPS in **FP16**; identity embedding runs on MPS in **FP32**. Tracking receives the sampled 1 fps sequence, as in this sampling configuration. This is not a full-frame-rate tracker evaluation.
- Match predictions to publisher boxes one-to-one at IoU ≥0.5. Maximize the number of valid matches before their total IoU. Wrong names for enrolled animals, names assigned to withheld animals, and named unmatched boxes are separate outcomes.
- Coverage denominators include every visible publisher annotation, including missed and unsuitable animals. Precision is undefined when nothing is named; zero wrong names alone is not a success.

Publisher annotations are numeric local conversions of the dataset's tracking labels. The original pickle is verified by hash, never deserialized here. These labels were not independently hand-audited in this experiment. Foundation-model training overlap is not completely auditable. Samples from one pen and neighboring frames are correlated; no confidence intervals or farm-level reliability claims are appropriate.

## Results

The initial detector was YOLO11s at 960 pixels and confidence 0.60. The alternative was the already cached YOLO26m-seg at 640 pixels and confidence 0.25. Both use ByteTrack and **bounding-box crops**; the alternative's segmentation masks are not used. This comparison changes detector weights, size and detection threshold together, so it does not isolate which change contributes most.

| Input to recognition | Visible known / unknown | Matched boxes | Eligible matched crops | Correct / wrong known names | Unknown / unmatched named |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial preset, 330–629 s | 1,800 / 600 | 97 / 2,400 (4.04%) | 94 / 2,400 (3.92%) | 0 / 0 | 0 / 0 |
| Publisher boxes + stable tracks, 330–629 s | 1,800 / 600 | 2,400 / 2,400 (oracle) | 671 / 2,400 (27.96%) | 21 / 0 | 0 / 0 |
| Alternative, 330–629 s | 1,800 / 600 | 650 / 2,400 (27.08%) | 345 / 2,400 (14.38%) | 0 / 0 | 0 / 0 |
| Frozen alternative, 930–1229 s | 1,795 / 598 | 569 / 2,393 (23.78%) | 321 / 2,393 (13.41%) | 0 / 0 | 0 / 0 |

The publisher-box control also supplies stable, anonymous track IDs. It is an **oracle diagnostic**, not something available to the app. It produces just 21 correctly named observations, all calf 3: 1.17% of visible known-calf observations. Even ideal localization and continuity do not make this early, three-example gallery effective under the unchanged policy. Only 28% of oracle boxes satisfy the crop geometry gates in the crowded pen.

The alternative produced 854 boxes in the first segment, including 204 unmatched boxes, and 835 boxes in the later segment, including 266 unmatched boxes. Extra detections therefore include uncertain or inaccurate localization; it would be misleading to call all additional boxes useful cows.

| Condition | Same cow changes track ID | Same track ID changes matched cow | Proposed-name switches |
| --- | ---: | ---: | ---: |
| Initial preset | 2 | 3 | 0 |
| Publisher boxes/stable tracks | 0 | 0 | 0 |
| Alternative, first segment | 11 | 16 | 0 |
| Alternative, later segment | 22 | 41 | 0 |

These switches compare adjacent matched observations separated by at most five seconds. They are diagnostic counts, not a complete MOTChallenge metric. More matched observations create more opportunities to count a switch. Zero name switches mainly reflects the absence of proposed names.

## Decision and next work

Use YOLO26m-seg, 640 pixels and confidence 0.25 for the revised experimental preset because it collects more localized cow crops on both segments. Keep the identity policy unchanged and require human confirmation. **This improves collection; it does not establish improved identification.** A clear passageway camera is a more suitable first trial than this crowded overhead pen.

The next bounded study should freeze a gallery with varied, independently confirmed views, then evaluate a separate day. Inspect crop quality and track continuity before changing matching logic. Mask-assisted crops, gallery adaptation and cattle-specific training remain candidates; none is validated by these results. Do not silently promote predicted names into enrollment, and do not tune thresholds on these query labels.

## Runtime and caching

On the development Mac, processing 300 sampled frames with fresh query embeddings took 24.29 seconds for the alternative's first segment and 24.72 seconds for the second. The first split spent 11.43 seconds in detection and 11.64 seconds in identity work; 474 crops were embedded. The second embedded 501 crops. Model construction, model download and gallery preparation precede these timers. These are sequential offline measurements with cached weights, not camera latency or multi-camera capacity claims.

The initial uncached baseline took 12.60 seconds. Its retained instrumented baseline repeats the same counts with warm embedding caches and takes 8.19 seconds; that number must not be compared as cold end-to-end inference speed. The oracle control takes 16.18 seconds and embeds 671 fresh crops.

The JSON-panel replay reused detector output and embeddings, reproduced all 300 baseline frame decisions exactly and performed **zero new encoder calls**, taking 1.39 seconds after initialization. Embedding caches use the production encoder fingerprint and image content. Cached speed is not inference speed.

The retained measurements and replay used detector-cache contract 2: video/model hashes, tracker config, detector options, device, Torch/Ultralytics versions and per-frame pixel hashes. A final provenance review strengthened the current script to contract 3, additionally keying Torchvision, OpenCV, NumPy, LAP and SciPy versions, including SciPy's absence. Contract 3 intentionally does not reuse the older tracking cache after a dependency change. No new accuracy run was performed for this cache-key-only change; the retained replay evidence describes contract 2.

## Reproduce and inspect

Use the application's Python 3.12 environment with its locked default dependencies, including OpenCV, Ultralytics and `lap`. The separate image-benchmark requirements alone do not include the video pipeline. Recorded package versions are in each summary: torch 2.12.1, torchvision 0.27.1, Ultralytics 8.4.80, timm 1.0.30, NumPy 2.5.0, Pillow 12.2.0, lap 0.5.13.

Download the public dataset video and its corresponding publisher annotation file; leave the pickle unopened. The included [numeric JSON panel](results/2026-10-03/video-annotations.json) contains only the 603 enrollment/query frame IDs and numeric boxes. It is an exact subset of the pre-existing local safe NPZ: all 4,817 boxes match after conversion to image coordinates. The prior pickle-to-NPZ conversion was **not independently recreated** in this run. The panel makes replay possible without that unavailable conversion utility or unpickling a downloaded file.

Annotation attribution: **tonyFang04, 8-calves**, [dataset source](https://huggingface.co/datasets/tonyFang04/8-calves), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Modification: selected numeric columns and the fixed temporal subset, serialized as JSON. Original annotation SHA-256: `2c5dbf9c7856bfb15fe38b99487ff576f1b281fcf70af84cc0ac982af1ef203e`. Video SHA-256: `475824794af23d28d9d92039eb893d73ab0374c8b3272d42c176b5f363cd9825`. Model revisions and checkpoint hashes are in [sources.json](sources.json) and each run manifest. No raw photos or video are redistributed.

From the repository root, after obtaining the files and official MIEWid checkpoint:

```sh
ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS=1 detector/.venv/bin/python \
  research/cow_identity/video_assessment.py \
  --video /path/to/pmfeed_4_3_16.mp4 \
  --source-pickle /path/to/pmfeed_4_3_16.pkl \
  --annotations research/cow_identity/results/2026-10-03/video-annotations.json \
  --detector /path/to/yolo26m-seg.pt \
  --weights /path/to/miewid-model.safetensors \
  --output .cache/cow-video-new-run --cache .cache/cow-video-cache \
  --device mps --mode alternate --start 330
```

Use a fresh output directory for every run. Use `--start 930` for the untouched later panel; `--mode preset --detector /path/to/yolo11s.pt` reproduces the original detector; `--mode oracle` uses publisher boxes and stable anonymous tracks. Reusing `--cache` avoids repeated embedding work. Each summary discloses detector-cache reuse and the number of fresh embeddings.

Compact manifests, summaries and prediction timelines are retained under `results/2026-10-03/video-{preset,oracle,alternate,alternate-later,json-replay}/`. Original measurements used the NPZ reader; the JSON reader was added afterward and its exact baseline replay is recorded in [video-replay-verification.json](results/2026-10-03/video-replay-verification.json). Two metric regression tests cover duplicate localization matches, missed animals, wrong known names, unknown names and switch-gap handling:

```sh
detector/.venv/bin/python -m unittest discover \
  -s research/cow_identity -p 'test_video_assessment.py'
```
