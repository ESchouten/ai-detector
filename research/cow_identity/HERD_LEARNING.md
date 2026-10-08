# Learning the herd: named cows on held-out barn video

This is the record of a method that names enrolled cows on barn video and refuses unknown ones: how it was developed, the protocol it was frozen under, and what it did on two held-out test videos. **At this commit the protocol is frozen and the test has not been run.**

## What changed against the earlier trials

Every earlier trial compared a crop with at most ten confirmed photographs of each animal, using a general animal encoder as published, and none named a useful share of the animals. This study changes nine things.

1. **The herd is learned.** Networks are adapted to the confirmed photographs by learning to sort them by cow. On later days of the same barn one such network puts 93–98% of crops with the right cow, where the published encoders reach 37–89% with the same photographs.
2. **A crop is compared with the photographs, as those networks describe them.** While it learns, a network also forms one direction per cow, and the first version of this study compared a crop with those directions. A stranger that looks like a confirmed cow then scores as high as some confirmed cows do. The mean similarity to a cow's two most similar photographs keeps them apart far better when one limit has to serve every herd (see [directions or photographs](#directions-or-photographs)).
3. **A cow gets hundreds of confirmed photographs**, from several days, both cameras, daylight and night. Fewer photographs lower both the share of animals named and the refusal of unknown animals (see [enrollment effort](#enrollment-effort)).
4. **The networks start from animals, not from general pictures.** A herd of ten teaches a network only the coarse differences between those ten. Starting from a backbone that was first taught 287 cows of other farms is what makes unknown animals refusable.
5. **Three such networks vote.** Networks taught from the same photographs in a different order disagree about a stranger far more than about a cow they know, so their mean similarity is lower for strangers and hardly lower for the herd.
6. **A second kind of network votes with them.** MIEWid, published for re-identifying animals of many species, is adapted to the herd in the same way. As published it names fewer animals than the cattle networks; adapted, it is fooled by different strangers than they are, and the mean of the two kinds leaves a wider gap between strangers and the herd than either alone (see [a second kind of network](#a-second-kind-of-network)).
7. **The networks see no colour.** With colour, a red stranger is taken for the herd's one red cow. Without it, daylight and infrared pictures also look alike to the networks.
8. **Night has its own limit.** Infrared light hides the contrast between a red coat and a white one, so strangers resemble the herd more at night than by day. A picture without any colour is an infrared one and asks for a higher similarity.
9. **The largest stock detector finds the cows.** The medium one misses cows lying behind cubicle rails; an animal that is not found cannot be named.

The rules that turn similarities into a shown name are otherwise the application's existing ones, with two changes: a confirmed name is held through weaker crops, and a track the detector misses for a moment keeps its agreement.

## Data, and what may be learned from when

The video is the public [ETH Zurich barn dataset](https://doi.org/10.3929/ethz-c-000796658) ([paper](https://doi.org/10.1016/j.biosystemseng.2026.104420)): thirteen adult Holstein cows, some red-and-white, in a free-stall barn seen from fixed cameras by day and, in infrared, by night. It has six tracking videos with one box and identity per cow per frame, and 7,889 identified crops taken from other recordings between 23 August and 10 September 2023. The publisher's crops stand in for photographs a farmer confirmed.

Three kinds of leakage were possible and are excluded:

- **Near copies.** A cow lies in one place for hours. The publisher's crops overlap the tracking videos in time: crops of 25 August match frames of video 3 pixel for pixel, and videos 1, 2 and 6 have crops taken 5–32 minutes away. A herd model used on a video therefore learns only from crops recorded **at least 24 hours before that video's first frame**. The publisher's own train/validation split is not used.
- **Unknown animals.** Cows 3, 4 and 12 are withheld. Their crops were resized along with the others and never shown to a model or looked at, and in development videos their boxes were left out of every count. Development simulated unknown animals by leaving three of the ten other cows out, in three different combinations.
- **Tuning on the test.** Videos 3 and 4 are development, 1 and 2 validation, 5 and 6 the test. Development never read a crop recorded within a day of a validation or test video. The test videos were opened once, after the protocol below was committed.

| Video | Recorded | Camera | Length | Role | Confirmed photographs available a day earlier |
| --- | --- | --- | --- | --- | --- |
| 3 | 25 Aug, 14:48 | 195, daylight | 30 min | Development | photographs a day before or after, in rotations of seven cows |
| 4 | 24 Aug, 20:18 | 197, infrared | 30 min | Development | as above |
| 2 | 26 Aug, 04:11 | 195, infrared | 5 min | Validation | 2,016 of ten cows, from 23–25 Aug |
| 1 | 27 Aug, 17:55 | 197, daylight | 5 min | Validation | 3,442 of ten cows, from 23–26 Aug |
| 6 | 28 Aug, 01:19 | 197, infrared | 60 min | Test | 3,753 of ten cows, from 23–27 Aug |
| 5 | 17 Sep, 13:29 | 195, daylight | 60 min | Test | 6,092 of ten cows, from 23 Aug–10 Sep |

Earlier work in this repository scored a different method on short windows of videos 3–6 (about four minutes of each) and had excluded videos 1 and 2 for a frame-count mismatch, which is an edit list that OpenCV already applies. Nothing in this study was chosen from those earlier scores, but videos 5 and 6 are not untouched by the project: they are held out from this method.

The starting weights were taught from MmCows, MultiCamCows2024 and Cows2021 photographs: 26,236 photographs of 287 cows of other farms, none from this barn. The detector is a stock COCO model.

## How a name is scored

Every box the application tracks in a sampled frame is paired one-to-one with a publisher box at an overlap of 0.5 or more. A shown name is **correct** only on the box paired with that cow. **Coverage** is the correct names divided by every annotated appearance of an enrolled cow, found or not.

The publisher boxes only the thirteen study cows, and not when more than half hidden or cut by the picture's edge. A named box without a partner is therefore not simply wrong. On the first validation video all fifteen such names were on the right cow: nine on a box drawn too loosely to pair, six on a cow the publisher had not boxed in that frame. Such a name is judged by the annotated animal its box lies on, which is the one it overlaps most, by at least 0.25:

| The unpaired box lies on | Counted as |
| --- | --- |
| The cow it names | Neither right nor wrong |
| Another enrolled cow | Wrong |
| A withheld cow | A named unknown animal |
| No annotated animal, while the named cow is annotated elsewhere in the frame | Wrong |
| No annotated animal, and the named cow is not annotated in the frame | Cannot be judged |

**Precision** is the correct names divided by the correct and the wrong ones, names on unknown animals included. The **conservative precision** counts every name on an unpaired box as wrong and is reported beside it as a lower bound. **Unknown animals named** is the share of annotated appearances of withheld cows that carry a name.

## The system that was measured

The measured system is the application's own code, not a research copy: the detector adapter with its tracker, the herd model's learning, and the identifier with its rules, configured by the shipped [Cow Identity preset](../../config/detector/cow-identity.json). A [runner](herd/app_run.py) feeds them one frame per second, shrunk as a camera source shrinks it, and records every box, the name shown on it and the similarities behind it. [Replaying](herd/app_score.py) the rules over those similarities reproduces every shown name, which is how each stage below is counted. A [second script](herd/app_smoke.py) starts the whole application with the preset and a two-minute development clip as its camera: it named 61% of the enrolled cows' appearances in those two minutes, start-up included, and none wrongly ([file](herd/results/development-application.json)).

| Stage | What it does | Measured as |
| --- | --- | --- |
| Localization | Stock YOLO26x-seg at 1280 pixels, confidence 0.1, one frame per second | Share of publisher boxes paired with a tracked box |
| Tracking | ByteTrack as shipped | Tracks per animal, tracks that cover two animals |
| Crop quality | Boxes at the picture's edge or under 32 pixels are no evidence | Share of annotated appearances whose box is fit |
| Enrollment | Publisher crops at least a day old, as confirmed photographs | Photographs and recorded clips per cow |
| Identification | Three DINOv2-small networks and one MIEWid network, colourless, adapted to the herd; mean similarity to a cow's two most similar photographs, the two kinds weighing the same | Share of fit crops that resemble their own cow most |
| Naming | A similarity limit by day and one by night, two animals claiming one cow both lose it, agreeing consecutive samples, a hold | Names shown, on whom |

## Development record

Everything here was measured on development data and chose the method. None of it is a result. Result files are in [`herd/results/`](herd/results/).

### Localization

The preset detected at 640 pixels with the medium model. On the daylight development video that finds 51% of the annotated cows: cows lying in cubicles are 100 pixels long at that size and are missed. At 1280 pixels the same model finds 90% ([640](herd/results/development-localization-640.json), [1280](herd/results/development-localization-1280.json)).

Through the application's detector and tracker, and without the withheld cows, the medium model finds 91% and the largest stock model 99.6%, with boxes fit to be evidence for 89% of the appearances instead of 79%, and it follows the same animals with 18 tracks instead of 35 ([file](herd/results/development-detector.json)). On the first validation video it finds 84% instead of 69% ([file](herd/results/validation-detector.json)); there the large model finds as many but lets two tracks slide from one cow to another, a lower confidence limit changes nothing, and a 1920-pixel input finds no more while drawing four times as many boxes on nothing annotated. No detector was trained.

### Published encoders with many photographs

With every available photograph as a reference instead of ten, the best published encoder (MIEWid) puts 74–85% of later-day crops with the right cow by nearest photograph and 75–89% with a linear layer on top; DINOv2 in three sizes and two resolutions reaches 37–72%. With limits chosen by leaving days and cows out, none names more than 7% of crops ([results](herd/results/)). More photographs help a fixed encoder, but an unknown cow lying in the same cubicle looks more like a photograph than the cow herself in a new pose.

### Adapting a network to the herd

A DINOv2-small adapted to seven cows puts 93–96% of later-day crops with the right cow after two or three passes over about 3,500 photographs ([crop-level runs](herd/results/development-finetune-crops.json)). Refusing unknown cows is the hard part. These were tried while a crop was still compared with learned directions:

| Tried | Outcome |
| --- | --- |
| Training four times longer | Same share right; every crop ends up near some cow's direction and unknown cows can no longer be told (upper bound on named crops 5% instead of 25%) |
| Each cow's mirrored photographs as an impostor class | Worse on both counts, with and without the background masked and full rotation: the network learns the mirrored training photographs, not coat layout |
| Masking the background with the detector's segmentation | No gain: coarse coat colour, not the stall, carries the false matches |
| Other farms' cows as extra classes while adapting | Later-day share right 96–98%, and the first setting in which development video passes |
| Other farms' cows taught first, then the herd alone | As good on video; needs no other farm's photographs on the farmer's computer. **Chosen** |
| That backbone kept fixed, only the last layer learned | Night coverage 45% instead of 61–65% at passing rules, and 7.5% of unknown animals named with a hold |
| The other farms' directions kept as fixed rivals | No gain and many more names on unannotated animals |
| 448-pixel input | One network took over 35 minutes on the Apple GPU; abandoned |

[Single-network video comparisons](herd/results/development-video-single-networks.json) put these side by side under one set of rules.

### Directions or photographs

Closed-set recognition was never the problem: with seven cows enrolled, nearly every fit crop resembles its own cow most. What fails is the limit below which a crop is refused. Against learned directions, an enrolled cow that has a look-alike in the herd scores lower than a cow without one, because the two directions are pushed apart, while a stranger that looks like an enrolled cow without a look-alike scores high. On one rotation two enrolled cows had median similarities of 0.65 and 0.69; on another a stranger reached 0.74. No single limit serves both, and the best rules that named no stranger in any of six development runs named 35% of the animals in the worst run and 58% on average ([file](herd/results/development-rules-directions.json)).

The networks' descriptions of the confirmed photographs do not have that distortion. On the same six runs, with one limit for all of them set where one in a hundred crops of the left-out cows passes in the worst run, 37% of the enrolled cows' fit crops pass in the worst run and 69% on average against directions; against the mean of a cow's two most similar photographs, 59% and 82% ([file](herd/results/development-directions-or-photographs.json)). One photograph does a little worse and could be a single wrongly confirmed one; three or five are no better at a stricter limit. Replayed through the rules of that time, photographs named 60% of the animals in the worst run and 69% on average without naming a stranger, where directions named 35% and 58%. [`similarity_study.py`](herd/similarity_study.py) repeats the crop-level comparison on models taught by the current application.

Normalising the scores with other farms' cows as a comparison group made them much worse, and so did asking the unadapted starting network for a second opinion: it puts 90–100% of crops with the right cow by nearest photograph, but cannot tell a stranger from the herd.

### How many networks

One cattle network alone passes 13–41% of the enrolled cows' crops in the worst of six runs at that shared limit, two together 46%, three 59%: a stranger's similarity drops as networks are added, the herd's hardly. On one rotation checked with up to five, the gain ends at three: from three to five the stranger's 99th percentile falls from 0.849 to 0.838 while the weakest enrolled cow's median falls from 0.85 to 0.83 ([file](herd/results/development-networks.json)).

### A second kind of network

MIEWid is the published encoder that did best in the earlier trials. As published, compared through its two nearest photographs under the same rules, it named 42% of the animals on the first validation video without naming a stranger; the three cattle networks named 53–66% there.

Adapting it at its published 440 pixels needed more memory than the computer used here has. At 288 pixels and eight photographs a step it needs about 6 GB and, for 2,000–3,400 photographs, seven to sixteen minutes on the Apple GPU. A tracked cow is seldom larger than 288 pixels in the application's picture.

One adapted MIEWid network is not safe alone: on one rotation it put a wrong enrolled cow's name on 130–150 crops at most limits, and by day its limit sits just above its highest-scoring stranger. But other strangers fool it than fool the cattle networks. On the night validation video the cattle networks' highest-scoring stranger reaches 0.85, inside the range of the herd's own medians (0.83–0.92); the adapted MIEWid's reaches 0.48, below every enrolled cow's median (0.51–0.67).

Two ways of combining the kinds were compared. Averaging them photograph by photograph, before a cow's two nearest photographs are taken, is what one long vector gives. Letting each kind take its own two nearest photographs and averaging the two scores is better: a cow's best matches are often different photographs for the two kinds, while a stranger scores low with one of them either way. At a limit of 0.68, with no stranger named by either, the first names 62% and 81% of the animals on the two validation videos and the second 67% and 93%.

The table sets the cattle networks alone against both kinds, on five development rotations and both validation videos, with five agreeing samples required ([file](herd/results/development-second-kind.json)). Each is given limits just clear of its own strangers: 0.84 by day and 0.88 by night for the cattle networks, 0.68 and 0.72 for both kinds.

| Run | Light | Cattle networks alone: highest limit that named a stranger | named at their limit | Both kinds: highest limit that named a stranger | named at their limit |
| --- | --- | --- | --- | --- | --- |
| Rotation 1, video 3 | day | 0.80 | 85% | 0.62 | 86% |
| Rotation 2, video 3 | day | below 0.80 | 82% | 0.58 | 81% |
| Rotation 3, video 3 | day | 0.82 | 79% | 0.58 | 78% |
| Validation video 1 | day | below 0.80 | 66% | below 0.58 | 67% |
| Rotation 1, video 4 | night | 0.87 | 61% | 0.64 | 77% |
| Rotation 2, video 4 | night | 0.83 | 88% | 0.58 | 80% |
| Validation video 2 | night | 0.83 | 64% | 0.62 | 83% |

The cattle networks' limits sit 0.02 and 0.01 above the highest limit at which they named a stranger; the limits for both kinds sit 0.06 and 0.08 above theirs, and name as many animals by day and, in two of the three night runs, more. The development rows of this table count the three withheld cows as strangers too, which the rest of development did not; the stranger named up to 0.87 is one of them. The animal networks behind these rows were taught by a trial script that preceded the application's own implementation of the same recipe; [`animal_trial.py`](herd/animal_trial.py) is a tidied copy of it.

### Colour

With colour, the three cattle networks named strangers in three of six development runs at a limit of 0.84 and in none at 0.85, five agreeing samples being required. Without colour none is named at 0.84, and in the three daylight runs none even at 0.82; the share of animals named at a given limit hardly changes ([file](herd/results/development-colour.json)). The daylight strangers that colour let through were red cows taken for the herd's red cow.

### Day and night

With the cattle networks alone, the highest limit at which a stranger was named was at most 0.82 in the daylight runs and 0.83–0.87 in the infrared ones. Under infrared light a red-and-white coat loses the contrast between its red and its white, and on the night validation video the strangers closest to being named are red cows taken for the herd's red cow. The application can tell the two lights apart: in the videos here every infrared frame has no colour at all in any pixel, and every daylight frame plenty. With both kinds of network the two lights differ less, 0.58–0.62 by day and 0.58–0.64 at night. The separate limit is kept to put the wider margin where look-alikes come closest and where the share of animals named can afford it.

### Rules

A policy written for this study (smoothed similarities, the stronger of two claimants keeps the name) passed on the first rotation with 44% night coverage. The application's own rules on the same similarities reached 58%: when two animals claim one cow **both** lose the name, so a look-alike never gathers the consecutive agreeing samples it needs while the real cow is in view. Their cost is the real cow's coverage in those moments.

Two changes to those rules were adopted:

- A **hold**: a track that was confirmed keeps its name through samples that fall short of a match while they still resemble that cow most, for a limited time after its last match and only while no other animal in view claims the cow.
- A track **missed for a moment keeps its agreement**. The application used to start a track over whenever one frame lacked it. With the same similarities that rule named 60% of the animals in the worst development run and 69% on average; keeping the agreement for up to five seconds names 67% and 75%, and no stranger in either case.

Three were tried and left out. Using boxes at the picture's edge as evidence named more animals but also 5% of the strangers in one run. Letting a confirmed track keep its confirmation when another animal claims its cow gained about one point and put more names on unannotated boxes. Ignoring a second box drawn on an already boxed animal, which the largest detector does for 6% of the animals, changed less than one point.

### Enrollment effort

One network per row, compared with directions, first rotation, seven cows ([file](herd/results/development-enrollment-effort.json)):

| Photographs per cow | Day: named / conservative precision / unknown named | Night: named / conservative precision / unknown named |
| --- | --- | --- |
| 13–15 | 28% / 98.7% / 0% | 20% / 88.0% / 4.3% |
| 41–43 | 59% / 97.1% / 5.6% | 51% / 98.6% / 0% |
| 133–147 | 53% / 95.6% / 8.5% | 53% / 99.1% / 0% |
| 251–329 | 65% / 99.7% / 0% | 65% / 99.2% / 0% |

These are single networks and vary from run to run, but the direction is plain: tens of photographs per cow are not enough.

### The chosen rules

[`tune.py`](herd/tune.py) replays the rules exactly over the five development rotations of the final system ([file](herd/results/development-rules.json)). With five agreeing samples, no stranger is named and no name is judged wrong from a limit of 0.64 upward in the three daylight rotations and from 0.66 in the two infrared ones; the highest limits that still named a stranger were 0.62 and 0.64. By day, three agreeing samples need a limit of 0.66 and eight allow 0.62. The hold changes little once a track keeps its agreement through a missed frame; it is set to five minutes.

The preset asks for 0.66 by day and 0.72 by night, five agreeing samples, and no lead over the next cow: with a cow scored by her two nearest photographs an enrolled look-alike scores high too, so a required lead costs the herd more than it costs strangers. At those limits the development rotations name 80–85% of the animals by day and 77–80% at night. One night rotation named an unannotated animal at the picture's edge as an enrolled cow for several minutes at limits up to 0.70; it looks like that cow, whom the publisher did not box in that video, but no annotation can settle it. The night limit of 0.72 is above that too.

### Validation

The two validation videos were run through the application's code with the frozen preset, alone on the Apple GPU ([video 2](herd/results/validation-video2.json), [video 1](herd/results/validation-video1.json), [judged](herd/results/validation.json)). The replay reproduced every shown name in both.

| | Video 2, night | Video 1, day |
| --- | --- | --- |
| Appearances of enrolled cows | 1,373 | 2,801 |
| Found by the detector | 1,368 | 2,478 |
| Named correctly | 1,070 (77.9%) | 1,902 (67.9%) |
| Named wrongly | 0 | 0 |
| Appearances of withheld cows, of which named | 608, 0 | 900, 0 |
| Names on boxes without a partner | 0 | 12: 7 on the named cow, 5 that cannot be judged |
| Precision, conservative precision | 100%, 100% | 100%, 99.4% |
| Seconds per frame: mean, 95th percentile, slowest | 0.31, 0.33, 0.57 | 0.45, 0.50, 0.73 |
| Learning | 8.6 minutes for 2,016 photographs | 14.6 minutes for 3,442 |

Both meet every criterion. Video 1 is the harder one: thirteen cows in view, two enrolled cows in the far row that are found half of the time and never named, and cows hidden behind others. A first pair of runs had taught other networks from the same photographs and named 84.9% on video 2 and, replayed at these limits, 66.6% on video 1: the share named moves by several points from one learning to the next. Replaying those runs at other limits showed the same edges as development. At night a stranger was named at limits up to 0.64 and none from 0.66; by day none at any limit from 0.60.

## Frozen protocol

The protocol was committed before either test video was opened, with the hashes of the preset, the weights and the videos ([`protocol.json`](herd/protocol.json)).

- **System.** The application's code at that commit with the shipped Cow Identity preset, run on an Apple GPU by [`app_run.py`](herd/app_run.py): YOLO26x-seg at 1280 pixels and ByteTrack, three cattle networks and one MIEWid network taught from the confirmed photographs, limits of 0.66 by day and 0.72 under infrared light, five agreeing samples, a hold of five minutes.
- **Animals.** Cows 0, 1, 5, 6, 7, 8, 9, 10, 11 and 13 are enrolled. Cows 3, 4 and 12 are withheld and count as unknown animals.
- **Confirmed photographs.** Every publisher crop of an enrolled cow recorded at least 24 hours before the video's first frame: 3,753 for video 6 and 6,092 for video 5.
- **Frames.** One per second over the whole hour of each video.
- **Scoring.** As described under [how a name is scored](#how-a-name-is-scored). Frames 17160–17519 of video 6, where the publisher gave cow 11 two boxes, count for neither box.
- **Criteria**, for each test video and for both pooled: precision of at least 99%, coverage of at least 60%, at most 1% of unknown animals' appearances named, and 95% of frames handled within one second, the time until the next frame arrives.
- **One run.** Each test video is run once and its result stands.

## Results

The test has not been run at this commit.

## Limits

- **One barn.** Thirteen Holstein cows, fixed cameras, three weeks. Nothing here says how the method does on another farm, breed, herd size or camera position.
- **Most of the herd was enrolled.** Ten of thirteen. Every unknown animal is a chance of a wrong name, and the margin against strangers was measured with three.
- **Hundreds of confirmed photographs per cow**, over several days, by day and by night, which a farmer has to confirm. The publisher's crops stood in for them; they come from the same barn and cameras but were not taken by the application.
- **A cow that is not found is not named.** Cows in the far row behind cubicle rails are missed even by the largest stock detector, and a box that touches the picture's edge is not used. On the first validation video that leaves two of ten enrolled cows unnamed for the whole video.
- **Night is harder.** Infrared light hides red-and-white patterns; the night limit is higher for that reason and rests on fewer animals than a real herd has.
- **Names on animals the publisher did not box cannot be judged.** They are left out of the precision and counted in the conservative one.
- **Learning needs a GPU and time.** After every change to the confirmed photographs the networks are taught again, which takes ten minutes to half an hour on an Apple GPU, and no name is shown meanwhile. The largest stock detector and the four networks together take about half a second per picture there.
- **Weights.** The cattle starting weights were taught from datasets published for non-commercial research and are not hosted anywhere yet; the preset names an address that does not exist. MIEWid is downloaded from its publisher.
- **Held out, not untouched.** Earlier work in this repository had scored another method on short windows of the test videos. The development figures for the second kind of network came from a trial script, not the application's code; the validation and test figures come from the application's code.

## Reproduce

Everything runs from the repository root in the detector's environment (`uv sync --extra default` in `detector/`). `$D` is the extracted dataset, `$W` a work folder.

```sh
python=detector/.venv/bin/python
herd=research/cow_identity/herd

# Photographs to confirm, and one frame per second of a video.
$python $herd/prepare.py photographs $D $W/photographs
$python $herd/prepare.py frames $D/tracking_new video6 $W/frames/video6

# One test video: learn the herd as it was a day before, name every frame, score.
$python $herd/app_run.py $W/photographs/classification.json --video video6 \
  --frames $W/frames/video6 --enrolled 0 1 5 6 7 8 9 10 11 13 \
  --preset config/detector/cow-identity.json --detector-weights yolo26x-seg.pt \
  --herd-weights cattle-dinov2-small.safetensors --animal-weights miewid-msv3.safetensors \
  --data $W/data-video6 --output $W/run-video6.json
$python $herd/app_score.py $W/run-video6.json --frames $W/frames/video6 \
  --labels $D/tracking_new --withheld 3 4 12 --output $herd/results/test-video6.json

# Both test videos against the protocol's criteria.
$python $herd/report.py $herd/results/test-video6.json $herd/results/test-video5.json \
  --protocol $herd/protocol.json --output $herd/results/test.json
```

The cattle starting weights come from [`auxiliary.py`](herd/auxiliary.py), which gathers the other farms' photographs, and [`pretrain.py`](herd/pretrain.py). Development used [`app_track.py`](herd/app_track.py) and [`app_scores.py`](herd/app_scores.py) for the rotations (`--either-side`), [`tune.py`](herd/tune.py) for the rules, [`app_localization.py`](herd/app_localization.py) for the detectors and [`similarity_study.py`](herd/similarity_study.py) for the ways of scoring. [`app_smoke.py`](herd/app_smoke.py) starts the whole application on a short clip. The tests beside the scripts run with `pytest` in that folder.
