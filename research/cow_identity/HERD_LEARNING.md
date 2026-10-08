# Learning the herd: named cows on held-out barn video

**The frozen system does not meet its protocol: it names too few animals at night.** On two held-out hours of public barn video, run once each, the names it showed were right 99.9% and 99.1% of the time, it named 2 of 10,712 appearances of unknown animals, and it handled 95% of the frames within 0.84 seconds on an Apple GPU. But it named 50.4% of the enrolled cows' appearances in the night video and 71.8% in the daylight one, 59.0% together, where the protocol asks for 60% in each.

| Criterion | Video 6, night | Video 5, day | Both |
| --- | --- | --- | --- |
| Precision at least 99% | 99.93% | 99.05% | 99.50% |
| Coverage at least 60% | **50.4%** | 71.8% | **59.0%** |
| At most 1% of unknown animals' appearances named | 0.02% | 0% | 0.02% |
| 95% of frames within one second | 0.84 s | 0.32 s | |

What is shown here is one barn with thirteen cows. The refusal of unknown animals held by a smaller margin than development suggested (see [after the fact](#after-the-fact)), so this is not yet a method to rely on, and nothing in it speaks for other farms.

The rest of this document is the record: how the method was developed, the protocol it was frozen under, and the test in detail.

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

The test ran once per video at the frozen commit, alone on the Apple GPU ([video 6](herd/results/test-video6.json), [video 5](herd/results/test-video5.json), [judged](herd/results/test.json)). It fails: coverage is under 60% in the night video and in both together. The other three criteria are met in both videos. The replay reproduced every shown name.

| | Video 6, night | Video 5, day |
| --- | --- | --- |
| Confirmed photographs | 3,753 | 6,092 |
| Learning | 15.9 minutes | 25.4 minutes |
| Appearances of enrolled cows | 26,752 | 17,808 |
| Found by the detector | 22,732 (85.0%) | 17,607 (98.9%) |
| With a box fit to be evidence | 22,655 | 14,508 |
| Resembling their own cow most | 21,985 | 14,420 |
| Named correctly | 13,494 (**50.4%**) | 12,785 (71.8%) |
| Named wrongly | 8 | 123 |
| Appearances of withheld cows | 8,103 | 2,609 |
| of which named | 2 (0.02%) | 0 |
| Names on boxes without a partner | 295: 64 on the named cow, 8 wrong, 1 on a withheld cow, 222 that cannot be judged | 195: 51 on the named cow, 123 wrong, 21 that cannot be judged |
| Precision | 99.93% | 99.05% |
| Conservative precision | 97.85% | 98.50% |
| Seconds per frame: mean, 95th percentile, slowest | 0.47, 0.84, 1.85 | 0.26, 0.32, 0.63 |
| Tracks on annotated animals, of which cover two animals | 124, 6 | 52, 3 |

Every wrong name in the daylight video is on a box without a partner: 57 lie on another annotated cow and 66 on no annotated animal while the named cow is boxed elsewhere in the frame. No paired box of an enrolled cow carries another cow's name in either video.

Named appearances per cow:

| Cow | Video 6, night | Video 5, day |
| --- | --- | --- |
| 0 | 0 of 3,602 | 795 of 2,075 (38%) |
| 1 | 0 of 3,541 | 1,464 of 2,340 (63%) |
| 5 | 3,193 of 3,602 (89%) | 648 of 2,124 (31%) |
| 6 | 2,959 of 3,083 (96%) | 1,416 of 1,975 (72%) |
| 7 | 1,626 of 3,197 (51%) | not in view |
| 8 | 1,633 of 1,689 (97%) | 3,592 of 3,602 (100%) |
| 9 | 702 of 2,756 (25%) | 2,158 of 2,514 (86%) |
| 10 | 147 of 209 (70%) | 944 of 1,313 (72%) |
| 11 | 1,135 of 2,632 (43%) | 1,768 of 1,865 (95%) |
| 13 | 2,099 of 2,441 (86%) | not in view |

### Where the animals were lost

In the night video two cows are never named in an hour, and they are 27% of all appearances. Cow 1 lies in the far row and is found in 13% of her appearances. Cow 0 is found in 99% of hers and resembles herself most in 97% of those crops, but her similarity stays between 0.54 and 0.65, under the night limit. Cows 9, 11 and 7 are named a quarter to half of the time for the same reason: their similarity moves around the limit. The other five are named 70–97% of the time. The validation video from the same camera had shown the same two cows unnamed; with the others named almost always, it still passed.

In the daylight video the largest loss is at the picture's edge: cow 5 is found in 96% of her appearances, but only 39% of those boxes are clear of the edge.

### After the fact

After scoring, the recorded similarities were replayed at other limits ([file](herd/results/test-after-the-fact.json)). This explains the result. It is not a result, and no limit read from it is a held-out one.

- **The margin against unknown animals was thinner than development showed.** In development and validation no stranger was named from a limit of 0.66 upward at night and 0.64 by day. In the night test video the withheld cows 4 and 12 score up to 0.77 and 0.78, and at a limit of 0.70 they would have been named in 286 of 8,103 appearances (3.5%). The night limit of 0.72 held by 0.02. By day the limit of 0.66 held by as much: at 0.64, 33 of 2,609 appearances (1.3%) would have been named.
- **No limit would have passed the night video.** Between 0.56 and 0.74 the share of animals named stays between 48% and 55%: at lower limits the strangers claim enrolled cows' names, and a contested name is taken from both. Two enrolled cows score no higher there than two of the strangers.
- **More photographs raised the strangers too.** The test herds were taught from 3,753 and 6,092 photographs, the validation herds from 2,016 and 3,442. A stranger compared with more photographs finds closer ones. The limits were chosen on smaller herds of photographs than they were tested on, and how they should move with the number of photographs was not measured.

## Names on another rule's events

Added after the test. A rule that detects behaviour, such as Cow Catcher's mounting model, boxes a scene and knows no animal. When a Cow Identity rule watches the same camera, the other rules' events now take the names of the cows that were inside their boxes. A cow counts when more than half of her box lay inside the event's box, in most of the pictures in which she was recognised while the event lasted and in at least two. Each of her boxes is compared with the event's box of the same moment, to within a second, because animals move.

**On the mounting example.** The repository has one mounting clip of eleven seconds. The mounting model's box is the mounting cow's own: typically 91% of her box lies inside it, and more than half in every picture. The mounted cow is found in pieces underneath, typically 63% inside and more than half in 71% of the pictures. A neighbour standing behind is typically 44% inside, and more than half in 26%.

The clip was then played in a loop as a live camera to the whole application, with a Cow Catcher and a Cow Identity detector on it and eight of its cows confirmed from the clip itself ([script](herd/mounting_live.py), [result](herd/results/mounting-live.json)). That shows the path from camera to recording; recognising cows from their own pictures through the published encoder is no test of recognition. All four mounting recordings made once the herd was loaded named the mounting cow, and first; one also named the mounted cow, who is "Cow 2" in the result, and none a neighbour, "Cow 4". An earlier run made six recordings and named the mounted cow in three. A first version of the rule asked for 70% inside in two pictures within five seconds of the event: it named the neighbour in 11 of 15 recordings, which is why the rule now compares the same moment and asks for most of the time.

So the mounting cow is named, and the mounted cow only sometimes: she is half hidden, her box breaks up, and boxes cannot tell her from a cow standing behind.

**On mounting pictures of other barns.** MOUNT-Cattle, under the MIT licence, has pictures of mounts in other barns; no cow in them is known, so they show only where the boxes fall ([script](herd/mounting_boxes.py), [result](herd/results/mounting-boxes.json)). The mounting model found a mount in 146 of the first 450 pictures. In 143 of them one cow's box from the stock detector overlapped the mounting box by at least half: there too the mounting box is one cow's box. A second cow lay more than half inside it in 106 pictures and a third in 34. Many of these pictures are neighbouring frames of the same scenes. A cow standing close is therefore inside the box in about a quarter of single pictures, here as on the example, and is named with the event when that lasts.

**Simulated on the barn videos.** No public mounting video has named cows. So the publisher's box of one animal stood in for an event's box, for every five seconds in which she stays annotated, and the names came from the application's runs of the validation and test videos through the detector's own code ([script](herd/event_names.py)). The test videos had been scored before. The rule was set on the mounting example; nothing was chosen on these four videos.

| Video | Events | Framed cow named | Nobody named | Another cow named: inside the box | overlapping it | not there | Events on unknown cows | Of those, named |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1, day, validation | 464 | 333 (72%) | 131 | 5 | 1 | 0 | 150 | 0 |
| 2, night, validation | 226 | 180 (80%) | 31 | 15 | 0 | 0 | 101 | 0 |
| 5, day, test | 2,954 | 2,235 (76%) | 716 | 2 | 0 | 13 | 432 | 1 |
| 6, night, test | 4,445 | 2,371 (53%) | 2,070 | 15 | 10 | 1 | 1,341 | 35 |

Over all 10,113 events, 14 carried the name of a cow who was not at the event's box at all: a wrong name. In 29 a real neighbour was named whose box, as the publisher drew it, lay mostly outside, and in 55 a cow who was inside. Every name on an event with an unknown cow belonged to an enrolled cow who really stood at that box. Events of three and of ten seconds give the same picture ([files](herd/results/)). How often the framed cow is named follows the share of animals the identity rule names at all.

This simulates the boxes, not the behaviour. The cows in it stand, walk and lie as in their confirmed photographs. A mounting cow rears up and hides half of the other, and a tracker confuses animals that overlap, so on real mounts fewer names and more wrong ones are to be expected. That has not been measured.

## What the method depends on

Added after the test, on development and validation video only. [`parts.py`](herd/parts.py) keeps what each network describes for a run, and [`parts_compare.py`](herd/parts_compare.py) combines kept descriptions into herd models without teaching again. Every combination gets its limits by the rule the frozen preset followed: the highest limit at which a development run named a stranger or a wrong cow, plus 0.04 by day and 0.08 at night. The shares below are of animals named at those limits; no combination then named a stranger or a wrong cow in any of the eight runs. One learning differs from the next by a few points.

### The cattle starting weights

The first kind of network starts from weights taught other farms' cows. They are a file of 89 MB that is not published anywhere, and the three datasets behind them forbid commercial use: MmCows under CC BY-NC-SA 4.0, MultiCamCows2024 and Cows2021 under the Non-Commercial Government Licence. Two other starts were tried ([file](herd/results/development-starting-weights.json)): DINOv2 as published, and weights taught the same way from SideViewCows2026 alone, which is under CC BY 4.0. Of that dataset 10,639 parlour photographs of 105 cows were on disk, a fifth of it, all taken from the right side (`auxiliary.py --any-use`).

| First kind starts from | Limits, day and night | Day: rotations 1–3, validation | Night: rotations 1–3, validation |
| --- | --- | --- | --- |
| The cattle weights, three networks, as frozen | 0.66, 0.72 | 85%, 82%, 80%, 68% | 77%, 80%, 68%, 83% |
| The cattle weights, one network | 0.66, 0.72 | 83%, 82%, 80%, 68% | 78%, 83%, 67%, 85% |
| CC BY cattle weights, one network | 0.68, 0.76 | 85%, 81%, 79%, 69% | 66%, 64%, 63%, 73% |
| Published DINOv2, one network | 0.72, 0.78 | 86%, 81%, 77%, 67% | 71%, 39%, 49%, 68% |
| Published DINOv2, three networks | 0.70, 0.78 | 85%, 81%, 80%, 68% | 63%, 41%, 48%, 47% |

By day the start makes no difference. At night it does: without cattle weights strangers score higher, the limit has to rise, and in the worst runs fewer than half of the animals are named. A fifth of one dataset with one view of the cow recovers part of that, and names 63–73% where the frozen weights name 67–85%.

Beside the second kind, one cattle network names as many animals as three. Three are kept: in four of the eight runs the highest limit at which they named a stranger is 0.02–0.04 lower than one network's, and the test showed how little margin there is.

### A processor alone

Timed on the processor of the computer used here, an Apple M2 Max on eight threads, with its GPU left out and other work running beside it: a learning step takes 1.8 seconds for a cattle network and 15 seconds for the second kind, which for 2,016 photographs comes to about three and a half hours where the GPU took nine minutes. Finding and following the cows in one picture takes 1.0 second and describing ten of them 1.3 seconds, so a picture a second is out of reach. The method needs a GPU.

Learning has only ever run on an Apple GPU. It needs about 6 GB of graphics memory beside the detector's own. An error in learning other than a missing file or a failed download ends the detector's process, and with it every other detector in that application until it is started again; too little graphics memory would be such an error and has not been tried.

## Limits

- **One barn.** Thirteen Holstein cows, fixed cameras, three weeks. Nothing here says how the method does on another farm, breed, herd size or camera position.
- **Most of the herd was enrolled.** Ten of thirteen. Every unknown animal is a chance of a wrong name, and the margin against strangers was measured with three.
- **Hundreds of confirmed photographs per cow**, over several days, by day and by night, which a farmer has to confirm. The publisher's crops stood in for them; they come from the same barn and cameras but were not taken by the application.
- **A cow that is not found is not named.** Cows in the far row behind cubicle rails are missed even by the largest stock detector, and a box that touches the picture's edge is not used. On the first validation video that leaves two of ten enrolled cows unnamed for the whole video.
- **Night is harder.** Infrared light hides red-and-white patterns. At night the test named half of the animals, and the limit that kept unknown animals out did so by a small margin.
- **The limits depend on how many photographs are confirmed.** They were set with two to three and a half thousand and held, narrowly, with four to six thousand. Nothing here says where they belong for a herd with fewer or more.
- **Names on animals the publisher did not box cannot be judged.** They are left out of the precision and counted in the conservative one.
- **Learning needs a GPU and time.** After every change to the confirmed photographs the networks are taught again, which takes ten minutes to half an hour on an Apple GPU, and no name is shown meanwhile. The largest stock detector and the four networks together take about half a second per picture there. A processor alone needs hours to learn and seconds per picture, and no other kind of GPU has been tried ([above](#a-processor-alone)).
- **Names on other rules' events were simulated.** No mounting video with known cows was available; see [above](#names-on-another-rules-events).
- **Weights.** The cattle starting weights were taught from datasets that forbid commercial use and are not published anywhere; the preset names an address that does not exist, so it cannot learn a herd as it stands. Without them the method names far fewer animals at night ([above](#the-cattle-starting-weights)). MIEWid is downloaded from its publisher, whose model card and repository state no licence.
- **Held out, not untouched, and now used.** Earlier work in this repository had scored another method on short windows of the test videos. The development figures for the second kind of network came from a trial script, not the application's code; the validation and test figures come from the application's code. Both test videos have now been seen by this method: a later version cannot be tested on them as on unseen video.

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

The cattle starting weights come from [`auxiliary.py`](herd/auxiliary.py), which gathers the other farms' photographs, and [`pretrain.py`](herd/pretrain.py). Development used [`app_track.py`](herd/app_track.py) and [`app_scores.py`](herd/app_scores.py) for the rotations (`--either-side`), [`tune.py`](herd/tune.py) for the rules, [`app_localization.py`](herd/app_localization.py) for the detectors and [`similarity_study.py`](herd/similarity_study.py) for the ways of scoring. [`app_smoke.py`](herd/app_smoke.py) starts the whole application on a short clip. [`event_names.py`](herd/event_names.py) simulates the names on another rule's events from a run that `app_run.py` wrote, and [`mounting_live.py`](herd/mounting_live.py) plays the mounting example to the whole application as a camera. The tests beside the scripts run with `pytest` in that folder.
