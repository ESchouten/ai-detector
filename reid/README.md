# Cow re-identification research

A standalone package for choosing and training a network that recognises individual cows on any user's farm, before any of it goes into the detector. It imports nothing from `detector/` and the detector imports nothing from it. The plan and the reasons behind it are in the project's `cow-reid/reid-plan.md`.

## Setup

```sh
cd reid
uv sync --extra models --extra video --extra tracking
```

PyPI's PyTorch uses the Apple GPU (MPS) on a Mac and CUDA on an NVIDIA computer; the benchmark picks CUDA, then MPS, then the processor, and warns when it falls back to the processor. `--device` overrides it.

## Data: one manifest per dataset

Every dataset is converted once into a CSV manifest of crops, one row per picture of one animal:

| Column | Required | Meaning |
|---|---|---|
| `path` | yes | Picture, relative to the manifest's folder |
| `identity` | yes | The animal's name or number |
| `session` | no | A day or a video, sortable as text (`2026-10-01`). Gallery and queries are split by session, so a cow is never compared with a picture of herself from the same minutes. Without sessions the split is random and every score is optimistic. |
| `camera` | no | Camera name |
| `track` | no | Crops of one continuous sighting; scored together at track level |
| `night` | no | `1`/`0`, `true`/`false` or `night`/`day` |

Most datasets carry their labels in folder and file names. `manifest-from-pattern` reads them with a regular expression with named groups `identity` and optionally `session`, `camera` and `track`; the default is one folder per animal. MultiCamCows2024, for example, is `2023AugDD/<cow>/<n>_<camera>.jpg`:

```sh
uv run reid manifest-from-pattern ~/datasets/MultiCamCows2024/root --out multicam.csv \
    --pattern '(?P<session>2023Aug\d\d)/(?P<identity>\d+)/\d+_(?P<camera>\d+)\.jpg$' \
    --night-from-colour
```

`--night-from-colour` marks pictures without colour as infrared night pictures.

Videos with a box and an animal number per frame, such as the ETH Zurich barn tracking videos, become crops with tracks (install the `video` extra):

```sh
uv run reid crops-from-video video3.mp4 video3_labels/ --session 2023-08-25 \
    --out ~/reid-cache/crops/eth --manifest eth-tracks.csv --append --every 30 --identity-prefix cow_
```

It keeps every 30th frame, skips boxes cut by the picture's edge or smaller than `--min-size`, and writes `<video>-preview.jpg` with the boxes drawn so you can check they line up with the frames (`--frame-offset` shifts them).

Unlabelled farm video becomes tracks with a stock YOLO26 segmentation model and ByteTrack (install the `tracking` extra). Each track is its own provisional identity until a person names it:

```sh
uv run reid tracks-from-video barn-2026-10-18.mp4 --session 2026-10-18 \
    --out ~/reid-cache/data/farm --manifest farm-tracks.csv --append --device mps
```

It keeps crops that are large (`--min-size`), clear of the picture's edge and at most 30% hidden behind other cows (`--max-covered`), and grays out everything outside the cow's mask so neighbours don't leak into her embedding (`--no-mask` keeps them). Night is judged on the whole frame. On the 11-second Cow Catcher clip it kept 4 clean tracks of the 10 cows in view; the others stood behind neighbours or at the edge.

Datasets and results stay out of git.

## Benchmark

The model has to work on farms it has never seen, so give the benchmark one manifest per farm and keep sets from one farm together when holding a farm out (the Bristol sets OpenCows2020, Cows2021 and MultiCamCows2024 probably come from the same university farm).

```sh
uv run reid benchmark ~/reid-cache/manifests/{eth-tracks,multicam,mmcows,opencows2020}.csv \
    --model megadescriptor-b-224 --model miewid-msv3 --model dinov2-b --half --out results
uv run reid report results/*.json
```

What happens on each farm:

1. **Time split.** The earliest sessions holding half of the crops become the gallery (the enrolled photos), later sessions the queries. `--gap-sessions 1` leaves a session out in between.
2. **Strangers.** In each of `--folds` folds, a different quarter (`--strangers`) of the animals loses its gallery photos. A correct answer for them is no name.
3. **Matching.** A query scores each enrolled animal by the mean similarity to her `--k` most similar gallery photos, and takes the best-scoring animal. With tracks, crop scores are averaged per track first.
4. **Naming.** A name is shown only above a threshold. With `--margin 0.5`, half the runner-up's score is first taken off the best animal's, so an animal that barely beats a look-alike is not named; rankings stay the same. Each threshold below is the lowest at which names are right `--precision` (99%) of the time on the data it was chosen on; they differ in what that data is.

The table reports, per model, farm and level (crop or track):

- **Rank-1, mAP**: closed-set ranking, comparable with papers. Rank-1 is per crop or per track like the rest of the row; mAP compares single pictures against the whole gallery, strangers' photos included, and is shown on crop rows only; on large sets it is estimated from 4,000 queries spread evenly over the list.
- **In top 3**: the cow is among the three best suggestions, for when a person confirms one with a tap.
- The naming columns read `named (right when named)`, in percent. Names given to strangers count as wrong.
  - **Own fold**: threshold chosen on the queries it is scored on. A ceiling.
  - **Other days**: the median threshold of the other folds, as a fixed setting behaves on the same farm on a new day with new strangers.
  - **Self-set**: chosen on the gallery alone, split again by time with some of its cows withheld. This is what an install can do by itself once the farmer has named their cows, so it is the number that matters for users' farms.
  - **Other farms**: the median of the other manifests' own thresholds, as a default shipped with the model would behave. Only filled in when several manifests are benchmarked together.
- **Day, night**: coverage of day and night queries separately at the self-set threshold, when the manifest says which is which.

Each run's JSON also keeps every fold's details and the thresholds themselves.

## Enrolment

The benchmark's gallery is labelled; a user's farm has none. `enroll` plays out how an install gets its gallery:

```sh
uv run reid enroll ~/reid-cache/manifests/eth-tracks.csv --model miewid-msv3 \
    --checkpoint ~/reid-cache/models/miewid-not-eth-6sets.safetensors \
    --enrol-sessions 2 --merge 0.5 0.6 0.7 0.8 --half --out results
```

1. **Sightings.** The crops of the first `--enrol-sessions` sessions are grouped into sightings, one per track; a crop without a track stands alone.
2. **Groups.** Sightings are grouped by look with average linkage, once for each `--merge` similarity.
3. **The farmer.** Groups with the most sightings come first, and each is named with one tap after the cow most of its pictures show, so the rest of a mixed group gets a wrong name. The farmer stops once `--goal` (90%) of the cows seen have a name. The labels are used only here and for scoring.
4. **Later days.** Each later session's sightings are named against that gallery at the threshold the install sets from it, as the benchmark's self-set threshold does, with the same `--precision` and `--margin`.

With `--coat 0 0.3`, every gallery is also scored with the coat-detail check below at each weight, in the install's threshold too; weight 0 is the embedding alone. It needs the `local` extra and matches about ten picture pairs a second on an M2 Max, so a farm with thousands of later sightings takes an hour or more; the counts are saved in `<out>/cache/` as it goes. Such a run also writes `pairs` into its JSON: each later sighting with its re-checked cows of the labelled gallery, the embedding's score, the coat matches, and whether it is the sighting's own cow.

With `--calibrate-from`, a mix calibrated on other farms is tried as one more coat variant, `calibrated`, after WildFusion: the pairs of the earlier runs given are pooled, isotonic regression maps the embedding's score and the coat matches each to the chance of the same cow, and a cow's score is the mean of both chances (cows not re-checked count as having no matches). The runner-up margin and the install's own threshold work on that score as on the others. Calibrate with runs on farms the model never saw and that differ from the one tested, for example ETH's run with the model that left ETH out for testing on Bristol's farms with the model that left them out, and the other way round.

With `--adapt`, the embedding is first adapted to the farm from its own enrolment sightings, without retraining, so an install can do it in seconds. Every kind takes the farm's mean sighting off each embedding, so the barn's shared look (floor, light, camera angle) stops making its cows alike, then damps the directions in which pictures vary on that farm: `whiten` learns them from all sightings, `tracks` from the pictures within each track (one cow, no labels needed), `names` from one cow's sightings on different occasions, by the farmer's names. `:shrink` sets how hard (`names:0.3` damps more than `names:3`); `center` only centres. `named` is `names` as ai-detector does it: the install's threshold check also centres on every enrolment sighting, not only the named ones it checks, and nothing changes until a cow is named on two occasions. Grouping still uses the plain embedding, so the taps are the same, and the install's threshold check learns the adaptation again from its own gallery part only.

With `--jointly`, later sightings in view at the same time are also named together: the surest first, and a name given to one is out of the running for the others, also as their runner-up, since one cow can't stand in two places. `--times` says how to tell when a crop was taken, as a regular expression with named groups `clip` and `frame` found in its path; sightings of the same clip and session whose frames overlap are in view together. For crops from `crops-from-video` that is `--times '/(?P<clip>[^/]+)-(?P<frame>\d{7})\.jpg$'`, for `tracks-from-video` `--times '/(?P<clip>[^/]+)-\d+/(?P<frame>\d+)\.jpg$'`. The table counts the sightings it names otherwise than naming each alone would. The install's threshold check is unchanged.

With `--anonymous`, the groups the farmer left unnamed also compete as anonymous cows: a later sighting most like one of them is not named, and one that beats them must also beat them as runner-up. The install's threshold check leaves them out.

With `--floor`, the install also raises its threshold just above every score at which one of its enrolment sightings, asked against the rest of the gallery, would be named after a cow seen beside it (found with `--times`), since that is certainly another cow. The table marks those rows `floor`, and the JSON keeps the floor. Scoring named sightings without their whole cow instead, as strangers, set the floor so high on ETH that only 2-13% of sightings were named.

`--check rotate` changes how the install checks its threshold: instead of asking the later half of its named sightings against the earlier half and taking the median of the folds' thresholds, it asks every enrolment session against all the others and sets one threshold on all the answers pooled, so a farm with a few days of sightings checks on every one of them.

With `--mix` (and `--check rotate`), the install also sets its threshold for its own share of strangers. The check withholds a fixed share of the named cows, which suits no farm exactly: a fully named herd has no strangers, and a farm whose unnamed cows are the hard ones has more. `--mix` scores the unnamed enrolment sightings against the gallery, estimates which share of them are strangers from how their best scores compare with the check's known cows and withheld strangers, and takes the lowest threshold whose names stay right `--precision` of the time at that share. The table marks those rows `for X strangers`, and the JSON keeps the share.

The table shows, per grouping, adaptation and coat weight or mix: groups formed, the share of sightings in a group named after their own cow, taps to the goal, to 90% and to every cow, then means over the later days: sightings named (right when named), cows recognised at least once that day, the right cow in the top 3, and wrong names in total. The first row is the same gallery named from the true labels, the ceiling for perfect naming. Each day's numbers are in the JSON.

## Coat details

The embedding sums up a whole cow, so two cows with similar coats can score alike. `rerank` re-checks each sighting's best `--top` candidates by matching coat details: ALIKED keypoints matched by LightGlue (install the `local` extra), between pictures of the sighting and each candidate's gallery pictures most similar to it. The count of confident matches, scaled to 0 to 1 at 100 matches, is added to the embedding's score with each `--weight`; weight 0 is the embedding alone.

```sh
uv sync --extra models --extra local
uv run reid rerank ~/reid-cache/manifests/eth-tracks.csv --model miewid-msv3 \
    --checkpoint ~/reid-cache/models/miewid-not-eth-6sets.safetensors --gallery-fraction 0.3 --out results
```

It uses one time split with a quarter of the cows as strangers, like the benchmark, and names at the threshold that is right 99% of the time on those same queries, with and without a 0.75 runner-up margin. That threshold flatters every row equally, so rows can be compared but are not what an install would get. Match counts are saved in `<out>/cache/`.

## Choosing a sighting's pictures

ai-detector keeps four pictures per track: the largest ones clear of the frame's edge and not largely under another box, spread over time. On a barn camera many of those still show only part of a cow, cut up by stall rails or merged with a neighbour. `track-pictures` tracks a video frame by frame with ai-detector's BoT-SORT tracker, keeps every tracked picture of every `--every`th frame and measures each: size, edge, the largest share under one other box, detection confidence, and the segmentation mask's pieces, solidity (its area over its convex hull's) and fill. `picture-choice` then compares ways of choosing, without labels:

```sh
uv run reid track-pictures ~/Downloads/barn.mp4 --session 2026-10-23 \
    --model yolo26m-seg.pt --out ~/reid-cache/pictures/barn --pictures barn-pictures.csv --device mps
uv run reid picture-choice barn-pictures.csv --model miewid-msv3 \
    --checkpoint ~/reid-cache/models/miewid-allfarms-100ep.safetensors --solidity 0.7 0.8 0.9 --out results
```

Each track is cut into `--window`-second stretches standing in for sightings. Two stretches of one track at least `--gap` seconds apart are the same cow; stretches of tracks seen in the same frame are different cows. Per way of choosing, the table gives how often a stretch's own cow outscores every cow in view with it, and how many same-cow pairs score above all but 1% of the different-cow pairs. A second table shows how single pictures fare by each measure, and a last line counts tracks whose first sighting has no whole picture but which show one later. Stretches of one track are easier to match than days apart, so the numbers rank the choices rather than predict naming.

## Naming a farm's cows

`groups` is the page a farmer would use: it groups every sighting in a manifest, for example the tracks `tracks-from-video` cut from a few days of barn video, and writes a page to name them.

```sh
uv run reid groups farm-tracks.csv --model miewid-msv3 \
    --checkpoint ~/reid-cache/models/miewid-allfarms-100ep.safetensors --merge 0.7 --out naming
open naming/index.html
uv run reid apply-names farm-tracks.csv naming/groups.csv ~/Downloads/names.csv --out farm-named.csv
```

The page shows the groups with the most sightings first, up to `--per-group` sightings each spread over the days. Type a cow's number and press Enter; click a picture of another cow to leave that sighting out. Names are kept in the browser until **Download names** saves `names.csv`. `apply-names` turns it into a manifest with the cows' numbers as identities, leaving out what wasn't named, so a test farm labelled this way can go straight into `enroll` or `benchmark`. A higher `--merge` gives smaller, purer groups at the cost of more typing.

## Fine-tuning

One backbone is trained on every farm but one, then tested on the farm it never saw:

```sh
uv run reid train ~/reid-cache/manifests/{multicam,mmcows,opencows2020}.csv \
    --model megadescriptor-b-224 --epochs 10 --out ~/reid-cache/models/md-b-not-eth.safetensors
uv run reid benchmark ~/reid-cache/manifests/eth-tracks.csv \
    --model megadescriptor-b-224 --checkpoint ~/reid-cache/models/md-b-not-eth.safetensors
```

Training uses sub-centre ArcFace on P×K batches (16 animals × 4 crops by default) with random crops and brightness changes but no mirroring, since a mirrored cow has a coat that doesn't exist. With several manifests, cow names are prefixed with the manifest's name and each batch holds cows of one farm only; cows from different barns are told apart by the barn, which teaches the network nothing about cows. With one manifest, `--until` keeps later sessions out of training so they stay fair for testing. Only the backbone is saved, after every epoch, so a crash late in a long run keeps the last finished epoch; a JSON file beside it records the settings, the farms, the epochs done and the loss per epoch. Any preset can be trained, MiewID included. Pictures are decoded on all processor cores; if the network runs out of memory, `--chunk 16` sends a batch through in parts and adds up their gradients, which changes only the batch-norm statistics.

On a barn camera most pictures show only part of a cow: a head at the feed fence, a cow behind rails or behind another cow (about 80% on the Pinken footage), while the public sets show mostly whole cows. `--partial 0.5` hides part of half the training pictures: it keeps only a band of the cow, filling the picture as her own box would, draws one to three rails across her in gray or a shade of steel, or paints a patch gray, as ai-detector paints what lies outside a cow's outline. `reid hide <manifest> --out <folder>` writes a copy of a test farm with every picture hidden the same way, to see how a network copes with partial cows; since it hides pictures as `--partial` trains on, it flatters a network trained that way, so real barn footage is the fairer test.

MiewID's weights come without a licence, so `efficientnetv2-m-440` is the same network starting from timm's Apache 2.0 ImageNet weights. Fine-tuning both on the same farms shows whether MiewID's animal pretraining still matters once the network has seen cows; if it doesn't, the second can be shipped without asking anyone.

## Using a model in ai-detector

`export-onnx` writes a preset, with its published weights or a fine-tuned checkpoint, as the ONNX model ai-detector's `individuals` setting takes, and checks that ONNX Runtime gives the same embeddings as PyTorch:

```sh
uv run --extra models --extra export reid export-onnx --model miewid-msv3 \
    --checkpoint ~/reid-cache/models/miewid-allfarms-100ep.safetensors \
    --out ~/reid-cache/onnx/miewid-allfarms-100ep.onnx
```

The model takes `images` (float32 RGB, N×3×H×W at the preset's size) and returns `embeddings`; its metadata holds the preset's `mean` and `std`. Share a fine-tuned MiewID only once Wild Me agrees.

`export-coat` writes the coat check's two networks, ALIKED (BSD 3-Clause) and LightGlue for ALIKED (Apache 2.0), as `keypoints.onnx` and `matcher.onnx`, then matches the given pictures in pairs with ONNX Runtime and with kornia and prints the largest differences:

```sh
uv run --extra local --extra export reid export-coat --out ~/reid-cache/onnx/coat \
    --pictures ~/reid-cache/crops/*.jpg
```

`keypoints.onnx` takes `image`, one float32 RGB picture as 1×3×H×W in 0 to 1 with its longer side 512, and returns `keypoints` (N×2 pixels) and `descriptors` (N×128). `matcher.onnx` takes `keypoints0`, `descriptors0`, `size0` (width, height) and the same for the second picture, each with a batch of one, and returns `scores`, each first keypoint's match confidence; the coat check counts those of at least 0.5. Both give kornia's keypoints and matches; only the keypoints' order differs.

## Caching

- Model weights download once into the Hugging Face and timm caches.
- Each model's embeddings of a manifest are saved under `<out>/cache/`, keyed by model, weights and the pictures' paths and modification times. A second run with other split or matching options takes seconds.
- `--max-per-identity N` takes a fixed sample per animal for quick comparisons.
- Pictures are decoded on all processor cores while the GPU runs the previous batch. `--half` runs the network in float16 on the GPU, roughly doubling speed; it is cached separately (`+fp16`).

## Models

| Preset | Network | Licence |
|---|---|---|
| `megadescriptor-l-384`, `-b-224`, `-t-224` | BVRA MegaDescriptor (Swin), trained on wildlife re-ID datasets | CC BY-NC 4.0 |
| `miewid-msv3` | Wild Me MiewID v3 (EfficientNetV2, 440 px), loaded with the code published beside the weights | None stated |
| `efficientnetv2-m-440` | The same EfficientNetV2 with ImageNet weights, as a start for fine-tuning | Apache 2.0 |
| `dinov2-s`, `-b`, `-l` | DINOv2 at 224 px | Apache 2.0 |
| `dinov3-s`, `-b`, `-l` | DINOv3 at 224 px; Hugging Face may ask to accept Meta's licence first | DINOv3 licence |
| `timm:<name>[@size]` | Any timm model; with `--checkpoint`, weights from a file (`.safetensors` or a PyTorch state dict) | — |

`--grayscale` drops colour before embedding. In the earlier herd study this kept red strangers from passing as the herd's red cow and made daylight and infrared pictures alike. For training, `--gray-chance 0.3` turns that share of pictures gray at random, so one network learns daylight colour and infrared night; the public sets hold few night pictures.

## Checks

```sh
uv run --group dev pytest
uv run --group dev ruff check . && uv run --group dev ruff format --check .
```
