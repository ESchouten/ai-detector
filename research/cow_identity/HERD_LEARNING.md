# Learning the herd: named cows on held-out barn video

**The frozen system does not meet its protocol: it names too few animals at night.** On two held-out hours of public barn video, run once each, the names it showed were right 99.9% and 99.1% of the time, it named 2 of 10,712 appearances of unknown animals, and it handled 95% of the frames within 0.84 seconds on an Apple GPU. But it named 50.4% of the enrolled cows' appearances in the night video and 71.8% in the daylight one, 59.0% together, where the protocol asks for 60% in each.

| Criterion | Video 6, night | Video 5, day | Both |
| --- | --- | --- | --- |
| Precision at least 99% | 99.93% | 99.05% | 99.50% |
| Coverage at least 60% | **50.4%** | 71.8% | **59.0%** |
| At most 1% of unknown animals' appearances named | 0.02% | 0% | 0.02% |
| 95% of frames within one second | 0.84 s | 0.32 s | |

What is shown here is one barn with thirteen cows, whose cameras see a cow whole and seldom behind another. The refusal of unknown animals held by a smaller margin than development suggested (see [after the fact](#after-the-fact)), so this is not yet a method to rely on.

**On a second farm it does not work.** Taken afterwards to another public pen, where a cow is half as large in the picture and the herd lies side by side in the cubicles, the application named 12% of the animals in validation video, 4–23% by camera, and no unknown cow. Two in three lying cows are not found there, and the cows that are found are not told apart; a sharper picture helps with neither. That farm's test hours were not run ([a second farm](#a-second-farm)).

**Seen from the ceiling, a herd of real size is told apart, and a passage is not a barn.** On a third public farm, in the publisher's own cut-outs of ninety cows that walk by under ceiling cameras, a herd of 67 is told apart almost as well as a herd of twelve: 98% of the pictures of two later days resemble their own cow most, none is taken for another cow, and one in 3,697 pictures of unknown cows passes. Run on that farm's footage of the race at five pictures a second, the application named a cow as herself 151 of the 208 times one walked by on two validation days, as another cow once, and no unknown cow. But a name stood on 29% to 51% of her pictures where the protocol asks for 60%, and where the cows queue a held name wandered onto a neighbour. Validation fails there, and that farm's two test days were not run ([a third farm](#a-third-farm)).

The rest of this document is the record: how the method was developed, the protocol it was frozen under, and the test in detail. Work done after the test is marked as such. Three parts of it changed what the application does: the recordings of other detectors carry the names of the cows in them ([names](#names-on-another-rules-events)); a cow is scored by a share of her photographs instead of a fixed two, with the limits that follow ([the number of photographs](#the-number-of-photographs)); and the photographs to review are taken over the hours instead of at once ([how many to start](#how-many-photographs-to-start)). No unseen video of the first barn is left to test any of that on.

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
- **More photographs raised the strangers too.** The test herds were taught from 3,753 and 6,092 photographs, the validation herds from 2,016 and 3,442. A stranger compared with more photographs finds closer ones. The limits were chosen on smaller herds of photographs than they were tested on. Measured since, this accounts for the whole of the thin margin by day and for 0.02 of the night's ([the number of photographs](#the-number-of-photographs)).

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

The first kind of network starts from weights taught other farms' cows. They are a file of 89 MB that is not published anywhere, and the three datasets behind them forbid commercial use: MmCows under CC BY-NC-SA 4.0, MultiCamCows2024 and Cows2021 under the Non-Commercial Government Licence. Two other starts were tried ([file](herd/results/development-starting-weights.json)): DINOv2 as published, and weights taught the same way from SideViewCows2026 alone, which is under CC BY 4.0. Of that dataset 10,639 parlour photographs of 105 cows were on disk, a fifth of it, all taken from the right side (`auxiliary.py --sources sideview`).

| First kind starts from | Limits, day and night | Day: rotations 1–3, validation | Night: rotations 1–3, validation |
| --- | --- | --- | --- |
| The cattle weights, three networks, as frozen | 0.66, 0.72 | 85%, 82%, 80%, 68% | 77%, 80%, 68%, 83% |
| The cattle weights, one network | 0.66, 0.72 | 83%, 82%, 80%, 68% | 78%, 83%, 67%, 85% |
| CC BY cattle weights, one network | 0.68, 0.76 | 85%, 81%, 79%, 69% | 66%, 64%, 63%, 73% |
| Published DINOv2, one network | 0.72, 0.78 | 86%, 81%, 77%, 67% | 71%, 39%, 49%, 68% |
| Published DINOv2, three networks | 0.70, 0.78 | 85%, 81%, 80%, 68% | 63%, 41%, 48%, 47% |

By day the start makes no difference. At night it does: without cattle weights strangers score higher, the limit has to rise, and in the worst runs fewer than half of the animals are named. A fifth of one dataset with one view of the cow recovers part of that, and names 63–73% where the frozen weights name 67–85%.

Beside the second kind, one cattle network names as many animals as three. Three are kept: in four of the eight runs the highest limit at which they named a stranger is 0.02–0.04 lower than one network's, and replayed over the test videos one network falls under 99% precision by day ([below](#the-number-of-photographs)).

**Taught without MmCows.** A herd of the [second farm](#a-second-farm) cannot start from weights that were taught that farm's cows. For it the weights were taught again from MultiCamCows2024, Cows2021 and SideViewCows2026: 24,075 photographs of 376 cows (`auxiliary.py --sources multicam cows2021 sideview`). With a cow scored by one in fifty of her photographs, as the application now does ([file](herd/results/development-weights-without-mmcows.json)):

| First kind starts from | Limits, day and night | Day: rotations 1–3, validation | Night: rotations 1–3, validation |
| --- | --- | --- | --- |
| The frozen cattle weights, three networks | 0.64, 0.70 | 85%, 82%, 78%, 68% | 76%, 80%, 68%, 84% |
| Weights taught without MmCows, three networks | 0.62, 0.70 | 82%, 82%, 80%, 68% | 77%, 79%, 77%, 84% |
| Those weights, one network | 0.66, 0.68 | 84%, 79%, 74%, 68% | 85%, 92%, 90%, 85% |
| The same network taught in a second order | 0.66, 0.74 | 83%, 81%, 77%, 68% | 68%, 36%, 62%, 67% |
| The same network taught in a third order | 0.64, 0.72 | 84%, 80%, 80%, 67% | 76%, 62%, 63%, 76% |

Three networks from either start do equally well; the preset's limits serve both, and are 0.02 stricter by day than the rule asks of the new weights. The last three rows are one network taught three times from the same weights and the same photographs, in a different order. At night the highest limit at which it still names a stranger moves between 0.60 and 0.66 from one learning to the next, and the share of animals named at the limit that follows moves between 36% and 92%. That, more than the average, is why three networks are kept.

**With rendered cattle.** A study of 2026 published a thousand rendered cattle, each seen from 128 sides ([MOO](https://github.com/TurtleSmoke/MOO)). Taught 32 views of each as well, from the horizontal upward, the starting weights know 1,376 animals instead of 376 (`auxiliary.py --sources multicam cows2021 sideview moo`). On development that reads as a gain at night ([file](herd/results/development-rendered-cattle.json)): the highest limit that names a stranger falls from 0.62 to 0.58, the rule's night limit with it from 0.70 to 0.66, and the share of animals named rises from 77–84% to 81–92%. It does not hold. Replayed over the two test videos, which had been scored before, the new weights at their limits name 49.6% of the animals at night where the frozen ones name 50.3%, and 285 of 8,103 appearances of unknown cows, 3.5%, where the frozen ones name none; by day 72.4% against 70.5%, and nine appearances of unknown cows ([`parts_from_run.py`](herd/parts_from_run.py), [file](herd/results/test-second-look-rendered-cattle.json)). The share named falls steeply just above the limit that keeps development's strangers out, so a limit that moves 0.04 moves the share by ten points, and the test video's strangers do not move with it. On the second farm the new weights tell the cows apart no better, 64% of the publisher's boxes against 66% ([below](#a-second-farm)). The dataset's own licence file forbids commercial use and derivatives, though its README names CC BY 4.0.

### MIEWid

The second kind is MIEWid as its publisher distributes it; neither the model card nor the repository states a licence. Its network is an EfficientNetV2-M, whose weights as published for ImageNet are under Apache-2.0. Started from those and adapted by the same recipe, it is of no use ([file](herd/results/development-second-kind-start.json)):

| Second kind | Limits, day and night | Day: rotations 1–3, validation | Night: rotations 1–3, validation |
| --- | --- | --- | --- |
| MIEWid, as frozen | 0.66, 0.72 | 85%, 82%, 80%, 68% | 77%, 80%, 68%, 83% |
| The same network as published for ImageNet | 0.90, 0.96 | 83%, 78%, 78%, 50% | 16%, 8%, 14%, 0% |
| None: the three cattle networks alone | 0.86, 0.90 | 85%, 81%, 79%, 53% | 54%, 29%, 44%, 55% |
| MIEWid alone | 0.52, 0.66 | 84%, 80%, 79%, 64% | 48%, 30%, 45%, 51% |

Alone, the ImageNet network cannot tell a stranger from the herd at any limit, and beside the cattle networks it does harm. What the second kind adds comes from having been taught to tell individual animals apart, not from its architecture. Neither kind does at night alone what the two do together.

### The number of photographs

The test scored a cow by her two most similar photographs. The more photographs she has, the closer the two nearest lie, for her own crops and for a stranger's alike, so limits chosen with one number of photographs are too low with more. In the eight development and validation runs, the highest limit at which a stranger or a wrong cow was named is 0.02 higher with all 170–440 photographs a cow than with 100 of them drawn at random in five runs, 0.06 higher in one and the same in two ([file](herd/results/development-nearest-share.json)).

A cow is now scored by one in fifty of her photographs, the most similar ones, and never fewer than two. With all photographs that score puts the highest unsafe limit where two of 100 put it, to within 0.02 in every run. The scores come out about 0.02 lower than the tested ones, and the rule that set the frozen limits sets them 0.02 lower too, at 0.64 by day and 0.70 at night; development and validation then name the same share of animals as before, within two points in every run, and no stranger.

For the test videos the crops were described again with the networks each run had taught ([`app_describe.py`](herd/app_describe.py)), which reproduces the recorded scores exactly, and scored both ways ([`rescore.py`](herd/rescore.py); [night](herd/results/test-video6-rescored.json), [day](herd/results/test-video5-rescored.json)). These are videos that were already scored: this explains the test, it is not a second one.

| | Video 6, night, 311–476 photographs a cow | Video 5, day, 423–758 photographs a cow |
| --- | --- | --- |
| Two nearest, as tested: limit | 0.72 | 0.66 |
| named, appearances of strangers named, precision | 50.4%, 2, 99.93% | 71.8%, 0, 99.05% |
| highest limit that still names a stranger | 0.74 | 0.64 |
| Nearest one in fifty: limit | 0.70 | 0.64 |
| named, appearances of strangers named, precision | 50.3%, 0, 99.95% | 70.5%, 0, 99.23% |
| highest limit that still names a stranger | 0.68 | 0.60 |

By day the new score puts the test where development was: no stranger is named from 0.62 upward, as in development from 0.62. At night the strangers of the test video still score 0.06 above those of development, with either score. The number of photographs explains the day; it does not explain the night.

With one cattle network in place of three, the same replay names 70.0% by day at 98.90% precision, under the criterion, and a stranger at the same limits as three.

### How many photographs to start

The development record found tens of photographs a cow too few, with one network that named a cow by her direction. The system as it is now was taught again on the two validation herds thinned at random to a fixed number of photographs a cow ([`parts.py --photographs`](herd/parts.py), [file](herd/results/validation-fewer-photographs.json)); thinned so, they stay spread over the same three or four days. At the limits of the preset:

| Photographs a cow | Video 1, day: named | highest limit that names a stranger or a wrong cow | Video 2, night: named | highest such limit |
| --- | --- | --- | --- | --- |
| All: 281–437 by day, 168–265 at night | 68% | 0.48 | 84% | 0.62 |
| 200 | 64% | 0.44 | 76% | 0.64 |
| 100 | 65% | 0.46 | 86% | 0.66 |
| 50 | 60% | 0.42 | 79% | 0.62 |
| 25 | 38% | 0.42 | 64% | 0.58 |

No stranger and no wrong cow was named at any size. Fewer photographs cost names, slowly down to fifty a cow and steeply below, and by night they bring the strangers closer to the limit of 0.70. Each row is one learning of one herd.

**From the application's own photographs.** The publisher's crops come from about fifty recordings of a cow a day, two crops from each. The application photographs every animal it follows once every thirty seconds, so a cow lying in one place gives 120 photographs of one occasion in an hour. [`app_enroll.py`](herd/app_enroll.py) makes the herd a farmer would have after reviewing a video: the application's own boxes of every followed animal, confirmed as the cow the publisher boxed there ([file](herd/results/validation-application-photographs.json)).

| Herd confirmed from | Photographs, cows, confirmations | Checked on | Named | Highest unsafe limit |
| --- | --- | --- | --- | --- |
| Videos 3 and 4, half an hour each: another camera or another light | 567, 9, 22 | Video 1, day | 22% | 0.52 |
| Video 4, half an hour: another camera | 296, 6, 9 | Video 2, night | 0% | 0.66 |
| Video 5, an hour: the same camera and light, 23 days later | 546, 8, 38 | Video 3, day | 8% | 0.58 |
| Video 6, an hour: the same camera and light, four days later | 825, 10, 81 | Video 4, night | 20% | 0.56 |

Again nobody was named wrongly, but hardly anybody was named: 60–120 photographs of a cow from one or two occasions do less than 25 from many. What counts is on how many occasions a cow was photographed, over how many days, on each camera and by day and by night; the number of photographs counts for little.

The application's collection worked against that. It stopped when 200 photographs waited for review, which with ten cows in view was after 15–22 minutes, and started again when the farmer made room. A farmer who reviewed every morning got a quarter of an hour of every morning and no photograph taken at night.

It now takes at most sixteen photographs an hour. Replayed over the two hour-long videos, that is one photograph of every cow in view at the start of the hour and a few of those that come into view after; the 200 then span about twelve hours, the night included, and every hour is another occasion. A herd collected that way over days has not been tried: the rows above are what a farmer got who reviewed without pause.

### A processor alone

Timed on the processor of the computer used here, an Apple M2 Max on eight threads, with its GPU left out and other work running beside it: a learning step takes 1.8 seconds for a cattle network and 15 seconds for the second kind, which for 2,016 photographs comes to about three and a half hours where the GPU took nine minutes. Finding and following the cows in one picture takes 1.0 second and describing ten of them 1.3 seconds, so a picture a second is out of reach. The method needs a GPU.

Learning has only ever run on an Apple GPU. It needs about 6 GB of graphics memory beside the detector's own. An error in learning other than a missing file or a failed download ends the detector's process, and with it every other detector in that application until it is started again; too little graphics memory would be such an error and has not been tried.

## A second farm

Added after the test. Both test videos of the first barn are used, so no later version can be tested there as on unseen video. This section takes the application as it stands after the changes above to another public farm, under the same criteria. **It fails there on validation video already, far below the share of animals it has to name, and the two test hours set aside for it were not run.**

### The pen

[MmCows](https://huggingface.co/datasets/neis-lab/mmcows), under CC BY-NC-SA 4.0, films one pen of sixteen Holstein cows for two weeks in July 2023, with four cameras that look into it from its corners. For one day, 25 July, the publisher boxed and numbered every cow in every fifteenth second of every camera from three in the night until midnight, wrote down what each cow did in every second, and published every camera's picture of every second. [`mmcows.py`](herd/mmcows.py) reads what is needed of it over the network.

| | The first barn | This pen |
| --- | --- | --- |
| Cows | 13, some red-and-white | 16, all black-and-white |
| A cow's longer side in the picture the application analyses | typically 220–320 pixels | typically 110–180 pixels |
| Appearances in which more than half of a cow's box lies inside another cow's | 0–10% | 20–57% |
| Night | infrared | lamps: the pictures keep their colour, so the night limit does not apply |
| Confirmed photographs | at least a day older than the video | of the same morning |

**Pictures.** A camera's picture is 4480 by 2800 pixels and is shrunk to the 1280 the application analyses. The publisher blacked out everything outside the pen in the pictures it labelled and boxed only the pen's cows; the pictures of every second show the neighbouring pens too, whose cows nobody numbered. The same area is blacked out here before the application sees a picture. The application has no such mask: without it, it would find those cows as well, and no label could judge a name on them.

**Photographs.** Cows are numbered on one day only, so the photographs cannot be a day older than the video. They are the publisher's boxes from 02:57 to 08:00, of every eighth labelled picture, which is one every two minutes, from all four cameras, cut as large as the application's picture shows them: 4,482 photographs of twelve cows, 223 to 438 of each, by lamp light and by daylight. No video starts before noon. The first barn asked for a day because a cow can lie in one place for hours; by the publisher's record of what each cow did, no cow is in a video as she was photographed. Between eight and noon every cow changed what she was doing at least 36 times, and the longest unbroken stretch that reaches into a video began at 10:03 ([`mmcows.py occasions`](herd/mmcows.py), [file](herd/results/mmcows-occasions.json)).

**Cows.** Every fourth cow by the publisher's number, 4, 8, 12 and 16, is withheld. The other twelve are enrolled.

**Starting weights.** The frozen cattle weights had been taught MmCows photographs of this very day, so they were taught again without it ([above](#the-cattle-starting-weights)). MIEWid's publisher describes it as taught 64 species of wildlife, and the list it gives has no cattle.

**Videos.** Validation is the half hour from noon and the hour from 14:00; the test would have been the hours from 17:00 and from 22:00, each on all four cameras. The herd is milked between 15:30 and 16:10, so by 17:00 no cow lies where she lay in a validation video. The application sees a picture a second, as in the first barn. What it shows is judged in the pictures the publisher boxed, one in fifteen.

### Validation

The half hour from noon ran through the application's code with the shipped preset, alone on the Apple GPU ([camera 1](herd/results/mmcows-validation-cam1.json), [2](herd/results/mmcows-validation-cam2.json), [3](herd/results/mmcows-validation-cam3.json), [4](herd/results/mmcows-validation-cam4.json)). The replay reproduced every shown name. Learning the herd took 27 minutes.

| | Camera 1 | Camera 2 | Camera 3 | Camera 4 | All four |
| --- | --- | --- | --- | --- | --- |
| Appearances of enrolled cows | 964 | 1,137 | 1,055 | 982 | 4,138 |
| Found by the detector | 658 (68%) | 588 (52%) | 533 (51%) | 550 (56%) | 2,329 (56%) |
| Resembling their own cow most | 541 | 471 | 345 | 427 | 1,784 |
| Similar enough for a name | 126 | 75 | 33 | 131 | 365 |
| Named correctly | 150 (15.6%) | 90 (7.9%) | 46 (4.4%) | 226 (23.0%) | 512 (**12.4%**) |
| Named wrongly | 3 | 3 | 0 | 0 | 6 |
| Appearances of withheld cows, of which named | 270, 0 | 227, 0 | 360, 0 | 417, 0 | 1,274, 0 |
| Precision | 98.0% | 96.8% | 100% | 100% | 98.8% |
| Seconds per frame: mean, 95th percentile, slowest | 0.47, 0.60, 0.91 | 0.49, 0.60, 0.86 | 0.45, 0.55, 0.64 | 0.49, 0.58, 0.83 | |

Where 60% of the appearances have to be named, 4–23% are. No unknown cow was named and every frame was handled within a second. Six names are wrong, which leaves the precision under 99% in two cameras and in the four together. More appearances are named than are similar enough, because a confirmed name is held through weaker crops.

With validation this far from the criteria, the hour from 14:00 was not run, and neither were the two test hours: they would have added a failure and used up the only unseen video of this farm. The hours from 17:00 and from 22:00 have not been shown to the application; their pictures were fetched and, for one camera, their labels counted.

### Why so few

**It is not the limit.** [`app_limits.py`](herd/app_limits.py) replays the four runs at other limits ([file](herd/results/mmcows-validation-limits.json)). At its best limit a camera names 33%, 26%, 14% and 28% of the appearances, and those limits, between 0.42 and 0.50, name dozens of strangers and wrong cows. Nor is the preset's limit safe here: one camera still names a wrong cow at 0.68.

**Lying cows are not found.** By the publisher's record, 53% of the enrolled cows' appearances in that half hour are of a cow lying down. They lie side by side in the cubicles and are seen from the side through the rails ([`mmcows.py postures`](herd/mmcows.py), [file](herd/results/mmcows-validation-postures.json)):

| Enrolled cows | Appearances | Found | Named correctly |
| --- | --- | --- | --- |
| Lying | 2,200 | 714 (32%) | 13 (0.6%) |
| On their feet | 1,938 | 1,615 (83%) | 499 (26%) |

The stock detector draws one box around several lying cows, or none. A larger input does not change that: on camera 3, with pictures twice as wide and a 1920-pixel input, it finds 37% of the lying cows instead of 34% and 76% of those on their feet instead of 74%, and takes 0.43 seconds a picture instead of 0.22 ([file](herd/results/mmcows-validation-detector.json)).

**The cows that are found are not told apart.** To set the detector aside, one network of each kind was taught from the morning's photographs and asked about the publisher's own boxes of that half hour, every other labelled picture: 2,066 crops of enrolled cows and 637 of withheld ones ([`mmcows_boxes.py`](herd/mmcows_boxes.py), [file](herd/results/mmcows-validation-boxes.json)). Photographs and crops were cut from pictures of three widths:

| Picture width | Crops that resemble their own cow most: all, lying, on her feet | Crops that also score above 99 in 100 strangers' crops |
| --- | --- | --- |
| 1280 pixels, as the application analyses | 66%, 52%, 82% | 25% |
| 2560 pixels | 68%, 56%, 83% | 23% |
| 4480 pixels, the camera's own | 68%, 55%, 82% | 23% |

In the first barn's test videos 97% and 99% of the crops fit to be evidence resembled their own cow most. Here a third do not, with every cow boxed by hand, and the camera's full resolution changes nothing: what the method lacks in this pen is not pixels but a view of the cow. Seen from a corner of the pen, a lying cow shows a strip of back between her neighbours and the cubicle rails, and a standing one is often half behind another.

**More photographs do not close the gap.** With the publisher's boxes of 18:00 to 22:00 added to the morning's, which lie between the two test hours and after the video they are asked about, there are 8,484 photographs in place of 4,482. Then 76% of the crops resemble their own cow most, 64% of the lying and 89% of those on their feet, and 19% score above 99 in 100 strangers' crops: the strangers come closer as well.

**Nor does cutting a cow out by her outline.** Where cows stand half behind each other a box holds parts of two animals, and the stock detector draws each cow's outline as well as her box. With the photographs and the crops cut as the application would cut them, by its own boxes, and everything outside the cow's outline blacked out, 69% of the crops resemble their own cow most instead of 64%, and of the cows on their feet 80% instead of 79%; 20% stand out from the strangers' crops either way ([`mmcows_outlines.py`](herd/mmcows_outlines.py), [file](herd/results/mmcows-validation-outlines.json)).

**The cameras look across the cows, not down on them.** A study of 2026 rendered a thousand cattle from 128 sides each and reports an angle, about thirty degrees above the horizontal, above which a network carries over far better to sides of a cow it was not taught ([MOO](https://arxiv.org/abs/2603.04314)). The publisher of this pen gives every camera's place and every cow's, so that angle is known for each appearance ([`mmcows.py angles`](herd/mmcows.py), [file](herd/results/mmcows-validation-angles.json)). The cameras hang 3.5 to 3.8 metres high at the corners of a rectangle of 24 by 12 metres. They see the cows from 13 degrees above the horizontal at the median, nine in ten appearances from under 18 degrees, and two in a thousand from above 30. Every lying cow is seen from between 8 and 20 degrees. Of the enrolled cows on their feet:

| Seen from | Appearances | Found | Named correctly |
| --- | --- | --- | --- |
| Under 12 degrees | 1,012 | 743 (73%) | 145 (14%) |
| 12 to 20 degrees | 678 | 625 (92%) | 255 (38%) |
| 20 to 30 degrees | 236 | 235 (100%) | 87 (37%) |
| Above 30 degrees | 12 | 12 | 12 |

A steeper view is also a nearer one in this pen, so the table does not tell the angle from the size of the cow, and twelve appearances are no measurement. But both farms fit the study. The first barn's cameras hang over the cubicles and look down on the cows' backs, and the two cows that were never named on its first validation video are in the far row, which that camera sees at its shallowest.

### What follows

- **The method is for a camera that looks down on each cow and sees her whole and apart from the others.** The first barn's cameras do; a camera in the corner of a pen, looking across the cubicles, does not. Barn cameras often hang where the second farm's do, so this difference matters more than any figure in this record. As a rule of thumb that both farms fit and neither proves: more than thirty degrees above the horizontal, which is a cow no farther away along the floor than one and a half times the camera's height above her back.
- **Lying cows need a detector that was taught to find them.** The stock one does not find them at any input size. None was trained here: this pen's own morning boxes could teach one, but a farmer has no boxes to give, and with the publisher's boxes the cows were still not told apart.
- **A herd's own photographs give such a camera away.** With each cow's latest fifth of photographs held back and one network taught the rest, 92% and 93% of the held-back photographs resemble their own cow most in the first barn's two validation herds, and 75% in this pen ([`held_back.py`](herd/held_back.py); [night herd](herd/results/held-back-video2.json), [day herd](herd/results/held-back-video1.json), [this pen](herd/results/held-back-mmcows.json)). That takes no video and no labels beyond the farmer's confirmations, one learning each; a second learning of the night herd gave 94%, so a point or two of it is chance. The application does not work it out. It could, when it learns a herd, and say that a camera does not show the cows well enough.
- **Two hours of this farm are unseen.** They are for a version that passes this validation first.

## A third farm

Added after the test. The second farm's cameras look across the cows. This section goes to a public farm whose cameras look straight down on them and whose herd is of real size: every measurement before this had ten or twelve cows enrolled. It first uses the publisher's own cut-outs of the cows, which say how well a herd is told apart once every cow is found and followed. It then runs the application on the footage of the two cameras over the race, where **validation fails and the two test days were not run.**

### The passage

[MultiCamCows2024](https://data.bris.ac.uk/data/dataset/2inu67jru7a6821kkgehxg3cv2), under the Non-Commercial Government Licence, films the passage along which ninety Holstein cows leave a milking parlour, with three cameras in the ceiling, around midday on seven days of August 2023 ([paper](https://arxiv.org/abs/2410.12695)). The publisher cut every cow's back out of five pictures a second, turned so that she walks to the right, checked every walk by hand and numbered the cows: 101,329 pictures. The cameras' footage is published beside them. [`multicam.py`](herd/multicam.py) reads the pictures and fetches the footage.

| | The first barn | The second pen | This passage |
| --- | --- | --- | --- |
| Cows | 13 | 16 | 90 |
| The cameras look | down on the cubicles | across the pen, from its corners | straight down |
| A cow's longer side in the picture the application analyses | typically 220–320 pixels | typically 110–180 pixels | typically 230–300 pixels |
| A cow is in view | for hours | for hours | typically for four to five seconds under each camera |
| Light | daylight and infrared | lamps and daylight | daylight |

By eye, about one cow in seven of this herd has a back that is all black or all white.

**Cows.** Every fourth cow by the publisher's number is withheld, 22 of them. One cow does not walk by before the sixth day, which leaves 67 to enrol. Herds of 12 and of 30 are drawn from those 67 so that each is part of the next.

**Photographs.** Eight pictures of every walk of an enrolled cow on the first three days, 14 to 16 August, spread over the walk: 43 to 72 of a cow, from up to nine walks.

**Asked about.** Every picture of every walk on 17 and 18 August, of the enrolled cows and of the withheld ones, twenty of whom walk by on those days, up to a walk's first twenty seconds. The last two days, 19 and 20 August, are kept unseen as a test. Of those days the files were counted, and two pictures of the empty passage were looked at before the days were divided.

**Starting weights.** The frozen cattle weights were taught eighty pictures of each of this farm's cows. Cows2021 comes from the same research group, filmed earlier on its university's farm, and neither paper says whether the herds share cows; so a herd of this farm starts from weights taught neither. That leaves the weights taught 105 cows of one German farm from the side ([above](#the-cattle-starting-weights)): they have seen no cow from above, and they are the only ones here whose photographs are under no non-commercial licence.

**Not untouched.** Earlier work in this repository compared published encoders on this dataset's pictures of 14 and 20 August, and another branch opened fourteen of its clips. Nothing of the herd method was chosen on this farm.

### A herd of real size

[`herd_size.py`](herd/herd_size.py) confirms a herd from those photographs, teaches it with the application's own code, three cattle networks and one MIEWid network, and scores every picture as the application scores a crop ([12 cows](herd/results/multicam-herd-of-12.json), [30](herd/results/multicam-herd-of-30.json), [67](herd/results/multicam-herd-of-67.json)). Similar enough means the preset's limit of 0.64.

| Herd | Photographs | Pictures of enrolled cows | that resemble their own cow most | and are similar enough | that resemble another cow and are similar enough | Pictures of withheld cows that are similar enough |
| --- | --- | --- | --- | --- | --- | --- |
| 12 cows | 814 | 2,317 | 99.96% | 97.4% | none | 604 of 3,697 (16.3%) |
| 30 cows | 2,038 | 5,958 | 99.5% | 89.1% | none | 4 of 3,697 (0.11%) |
| 67 cows | 4,465 | 12,606 | 98.3% | 85.0% | none | 1 of 3,697 (0.03%) |

**Seen from above, a herd of 67 is told apart.** In the first barn's test videos 97% and 99% of the crops fit to be evidence resembled their own cow most, with ten cows enrolled; in the second pen 66% of the publisher's boxes did, with twelve. Here 98% do with 67, and no picture that passes the limit is taken for another cow.

**A larger herd costs names, slowly.** The twelve cows of the smallest herd are similar enough in 97%, 93% and 87% of their pictures as the herd grows around them.

**It is the small herd that names unknown cows.** One of the twelve, cow 6, has an all-black back. So have the withheld cows 32 and 36, and 88% and 97% of their pictures are taken for cow 6. Asking for a lead over the next most similar cow does not stop that: with a lead of 0.3 asked, as many pass. With thirty cows enrolled, four of them black or nearly so, one of those two cows' 614 pictures passes, and with 67 none: the networks have had to tell black cows apart, and an unknown one no longer resembles any of them enough. A herd of which a part is confirmed is the dangerous one, and the plain cows in it most of all.

**Plain cows are named less, not wrongly.** In the herd of 67, thirteen cows are similar enough in fewer than four in five of their pictures, and by eye eight of those have a back that is all or nearly all of one colour. The all-black cow 77 is similar enough in 3 of her 55 pictures. None of their pictures passes the limit as another cow.

**The limit of the first barn holds here about as it held there.** For the herd of 67, at 0.60, 6 of the withheld cows' 3,697 pictures pass and 3 of the enrolled cows' 12,606 are taken for another cow; at 0.54, 116 and 32. The herd of 30 is closer to the edge: at 0.60, 51 of the withheld cows' pictures pass, 1.4%. The first barn's development runs still named a stranger at 0.62 by day.

**By camera** 96%, 88% and 79% of the pictures are similar enough. The first two cameras look down on a narrow race; under the third the passage widens, and cows stop and turn there.

### A cow that walks by

A cow is under one of these cameras for four to five seconds, typically: 20 to 23 of the publisher's pictures. The preset looks once a second and shows a name when five pictures in a row agree. Counted with that rule on the publisher's pictures, and taking a name to be held to the end of the walk once it is shown:

| Herd | Walks of enrolled cows | Named as herself: at one picture a second, at five | Named as another cow | Walks of withheld cows named, of 99: at one, at five | Pictures that carry her name: at one, at five |
| --- | --- | --- | --- | --- | --- |
| 12 cows | 60 | 32, 60 | none | 7, 13 | 49%, 88% |
| 30 cows | 144 | 75, 143 | none | none | 44%, 83% |
| 67 cows | 312 | 151, 300 | none | none | 42%, 82% |

At one picture a second half of the walks end before five pictures have agreed, and four in ten pictures carry a name where the criteria ask for six. At five a second nearly every walk is named. The preset as shipped suits cows that stay in view. A camera over a passage needs about five pictures a second, which leaves 0.2 seconds for one; with the preset's detector at its 1280 pixels the application needs more than that for one picture in twenty ([below](#development-on-the-third-day)).

### Fewer photographs

With two photographs of each walk instead of eight, 12 to 18 of a cow, the herd of 67 is still sorted: 97% of the pictures resemble their own cow most, none passes as another cow, and no withheld cow's picture passes. But only 53% are similar enough, and at five pictures a second 222 of 312 walks are named, with 53% of the pictures carrying a name ([file](herd/results/multicam-herd-of-67-two-photographs-a-walk.json)). A camera that sees every cow alike still needs dozens of photographs of each.

### The footage

The cut-outs say who a cow is, not where in the cameras' footage she was cut from, so a name shown on the footage could not be judged. A cut-out is the frame's own pixels, turned. [`multicam_locate.py`](herd/multicam_locate.py) matches the details of a picture with those of every frame in which something as large as a cow has changed, fits a turn and a shift to them, lays the frame under the picture and compares the two grey level by grey level: a picture differs from the frame it was cut from by five to eight levels. A cow that stands still fits a row of frames, so every close fit is kept, and [`multicam_fill.py`](herd/multicam_fill.py) gives each walk's pictures frames that rise in the order they were taken, their own frames first, and looks for the rest between their neighbours.

**Cameras.** The first two cameras look down on the race, where the cows walk one behind the other. The third looks down on the area behind it, where the herd stands packed. When this was set up the [trial guide](README.md#try-the-existing-appearance-gallery-preset) gave a camera over a passage as its example, so the two race cameras are the test. That was decided before the application was run on any of them, and the third camera's pictures were not placed.

**What was found again.** Of the 28,960 pictures of those two cameras on the five days that may be opened, 28,401 get a frame of their own, 95% to 100% by camera and day, and every walk of every cow has at least one ([file](herd/results/multicam-pictures-placed.json)). The footage of the last two days was not fetched.

**Labels.** A cut-out ends at the cow's shoulders. Her label is the upright box around it, lengthened by a third of its length towards her head. A name is judged as in the first barn ([how a name is scored](#how-a-name-is-scored)), in every picture of a session. A cow whom the publisher did not cut out of a frame, mostly because another overlapped her, has no label there.

**Photographs.** Eight pictures of every walk under the two cameras, spread over the walk and cut out of their frames by that box, as large as the application sees them. The validation days learn from the first three days, 2,990 photographs of 67 cows, 32 to 48 of each. The development day learns from the two days before it, 2,110 photographs, 16 to 32 of each.

**Five pictures a second.** [`passage.json`](herd/passage.json) is the shipped preset with three settings changed: a picture every 0.2 seconds, every one of them a sample for the identity, and the detector's input at 960 pixels instead of 1280. The research scripts took a picture a second whatever the preset said; they now take the preset's interval, and with the shipped preset reproduce the first barn's recorded scores exactly.

### Development on the third day

The busiest ten minutes under each camera on 16 August, 3,000 pictures each, were used to settle that preset.

**The detector.** Stock detectors of two sizes at three inputs, through the application's tracker ([file](herd/results/multicam-development-detectors.json)). Found is the share of labelled cows with a tracked box on them. Could carry a name is the share of her pictures that come after five fit pictures in a row and before her box touches the picture's edge, which is where the application's rules let a name stand if she is recognised at once.

| Detector and input | Camera 1: found, with a fit box, could carry a name | Camera 2: found, with a fit box, could carry a name |
| --- | --- | --- |
| Medium, 640 pixels | 82%, 65%, 50% | 62%, 62%, 55% |
| Medium, 960 | 84%, 64%, 52% | 65%, 63%, 57% |
| Medium, 1280 | 87%, 71%, 57% | 54%, 52%, 46% |
| Large, 640 | 84%, 62%, 51% | 72%, 70%, 66% |
| Large, 960 | 82%, 62%, 51% | 77%, 75%, 72% |
| Large, 1280, the preset's | 78%, 58%, 48% | 77%, 75%, 70% |

The second camera's picture is hazy, and there the large detector finds far more cows than the medium one. The large one at 960 pixels is taken. At 1280 the application needed more than 0.2 seconds for one picture in twenty under the second camera ([file](herd/results/multicam-development-camera2-detector-at-1280.json)). The tracker passes from one cow to the next in one or two of some 25 tracks; at a picture a second another branch of this repository had seen that in three of eight.

**The application** with that preset ([camera 1](herd/results/multicam-development-camera1.json), [camera 2](herd/results/multicam-development-camera2.json), [walk by walk](herd/results/multicam-development-walks.json)). The replay reproduced every shown name.

| | Camera 1 | Camera 2 |
| --- | --- | --- |
| Pictures of enrolled cows | 440 | 1,580 |
| Found | 363 | 1,221 |
| With a box fit to be evidence | 265 | 1,192 |
| Resembling their own cow most | 257 | 969 |
| Similar enough for a name | 180 | 234 |
| Carrying her name | 129 (29%) | 242 (15%) |
| Carrying another cow's name | 0 | 0, and 1 on a box without a partner |
| Pictures of unknown cows, of which named | 201, 0 | 70, 0 |
| Enrolled cows that walk by: named as herself, as another cow | 17: 16, 0 | 12: 9, 0 |
| Unknown cows that walk by, of which named | 6, 0 | 3, 0 |
| Seconds a picture: mean, 95th percentile | 0.09, 0.18 | 0.12, 0.20 |

Nearly every cow that walks by is named, and none wrongly. But a name stands on 29% and 15% of her pictures, where the criteria ask for 60%. Three things account for it.

- **The rules were made for cows that stay.** A cow is in view for four to five seconds. Her name is shown after five agreeing pictures and dropped when her box touches the picture's edge, as it does on her way out. Under the first camera that leaves half of her pictures in which a name could stand at all.
- **One cow that stands still outweighs a herd that walks.** Under the second camera cows queue. Cow 6, whose back is all black, stood there for 812 of the 1,580 pictures; she was found in 683 of them and never similar enough for a name.
- **Two days of photographs are few.** Of the fit pictures under the first camera, 97% resemble their own cow most but 68% are similar enough.

**A name kept at the edge.** [`app_what_if.py`](herd/app_what_if.py) replays a run with a rule changed. Keeping a confirmed name for two seconds after the last whole view of a cow, instead of dropping it at the edge, puts a name on 45% of her pictures under the first camera instead of 29%, with no name wrong and no unknown cow named ([file](herd/results/multicam-development-name-kept-at-the-edge.json)). It is no rule for a barn: replayed over the first barn's four application runs, it names 73.3% instead of 71.8% of the animals in the daylight test video, and 143 wrongly instead of 123, which takes the precision from 99.05% to 98.92% ([file](herd/results/first-barn-name-kept-at-the-edge.json)). The application was not changed.

### Validation on the fourth and fifth day

The whole sessions of 17 and 18 August under both cameras ran through the application's code with that preset, alone on the Apple GPU, with a herd learned from the first three days in thirteen minutes ([17 August, camera 1](herd/results/multicam-validation-17-august-camera1.json), [camera 2](herd/results/multicam-validation-17-august-camera2.json), [18 August, camera 1](herd/results/multicam-validation-18-august-camera1.json), [camera 2](herd/results/multicam-validation-18-august-camera2.json), [walk by walk](herd/results/multicam-validation-walks.json), [judged](herd/results/multicam-validation.json) against [`protocol-passage.json`](herd/protocol-passage.json)). The replay reproduced every shown name in all four.

| | 17 August, camera 1 | 17 August, camera 2 | 18 August, camera 1 | 18 August, camera 2 |
| --- | --- | --- | --- | --- |
| Pictures of the session | 20,965 | 25,481 | 21,482 | 25,008 |
| Pictures of enrolled cows | 906 | 1,966 | 2,007 | 3,957 |
| Found | 643 (71%) | 1,059 (54%) | 1,554 (77%) | 2,935 (74%) |
| With a box fit to be evidence | 493 | 1,022 | 1,307 | 2,814 |
| Resembling their own cow most | 489 | 1,021 | 1,287 | 2,708 |
| Similar enough for a name | 417 | 713 | 1,006 | 1,866 |
| Carrying her name | 266 (**29.4%**) | 761 (**38.7%**) | 818 (**40.8%**) | 2,006 (**50.7%**) |
| Carrying another cow's name | 0 | 0 | 0 | 73 |
| Pictures of unknown cows, of which named | 312, 0 | 983, 0 | 995, 0 | 1,351, 0 |
| Names on boxes without a partner | 36: 29 on the named cow, 7 that cannot be judged | 1,077: 613 on the named cow, 9 wrong, 2 on an unknown cow, 453 that cannot be judged | 195: 62 on the named cow, 1 wrong, 132 that cannot be judged | 1,866: 579 on the named cow, 289 wrong, 4 on an unknown cow, 994 that cannot be judged |
| Precision | 100% | 98.58% | 99.88% | **84.57%** |
| Enrolled cows that walk by | 42 | 42 | 62 | 62 |
| named as herself | 33 | 30 | 47 | 41 |
| named as another cow | 0 | 0 | 0 | 1 |
| Unknown cows that walk by, of which named | 13, 0 | 13, 0 | 20, 0 | 20, 0 |
| Seconds a picture: mean, 95th percentile, slowest | 0.09, 0.16, 0.51 | 0.09, 0.18, 0.32 | 0.12, **0.21**, 0.37 | 0.09, 0.19, 0.34 |
| Tracks on labelled cows, of which cover two | 60, 1 | 59, 3 | 89, 3 | 83, 6 |

**It fails**: in every session on the share of pictures that carry a name, 29% to 51% where 60% is asked, and in three of the four on something else as well. The two test days were therefore not run, and their footage was not fetched. The 174 published pictures of enrolled cows that got no frame are not among those counted; taken as unnamed they lower a session's share by 1.6 points at most.

**Over the race it names three cows in four and none wrongly.** Under the first camera 80 of the 104 cows that walked by on the two days were named as themselves, none as another cow, and none of the 33 unknown cows that walked by. Of the names on paired boxes none was wrong. Of the crops fit to be evidence 99% and 98% resemble their own cow most on the two days, as in the cut-outs, and 85% and 77% are similar enough for a name. Cows 1, 6 and 7, whose backs are all white or all black, were named in none of the four sessions.

**Where the cows queue, a name wanders.** Under the second camera the cows stand packed at the end of the race, and there the tracker slides from a cow onto her neighbour: 9 of its 142 tracks cover two cows. On 18 August a track that had been named cow 42 slid onto cow 37 beside her. Her crops resembled cow 42 more than any other cow, though far too little for a name, and the five-minute hold kept the name on her: 73 pictures of cow 37 carry it, and 289 names on boxes without a partner are wrong as well. That session's precision is 84.6%. Replayed without the hold it names 8 pictures wrongly instead of 362, and 35% instead of 51% ([file](herd/results/multicam-validation-without-the-hold.json)): the hold is also what names a cow that stands in a queue.

**The time is tight.** At five pictures a second 0.2 seconds are available for one. The session that needed 0.21 for one picture in twenty had animals in the pens beside the race in view throughout: 15,942 of its 20,209 boxes lie left of the race, followed all session and never named (counted in the run, which is not kept here). The application cannot be told to leave a part of the picture out.

**What the share of pictures measures here.** A cow is under a camera for four to five seconds. She is named a second after she is found and loses the name when her box touches the edge on her way out, so about half of her pictures could carry a name at all. With the name kept for two seconds at the edge, the first camera's sessions come to 42% and 51% with no more wrong names; the second camera's gain two points at most, and on 17 August eight wrong names and six on unknown cows more ([file](herd/results/multicam-validation-name-kept-at-the-edge.json)).

### What follows

- **Seen from above, a herd of real size is told apart**: 98% of the publisher's cut-outs resemble their own cow most with 67 cows enrolled, and so do 96% to 100% of the crops that the application itself cuts from the footage. That is the camera the [second farm](#what-follows) pointed to, on a farm chosen for its cameras before the method was run on it.
- **A camera over a passage tells who walked by.** Of 208 times an enrolled cow walked by under a camera on the two validation days she was named as herself 151 times, as another cow once, and of 66 times an unknown cow walked by she was named in none.
- **It does not meet the criteria there, and as the application is it cannot.** The share of pictures that carry a name was made for cows that stay in view. A cow that walks by is named for a second or two of her four.
- **A passage needs what the application does not have.** Five pictures a second, which a preset can ask for. A name that outlasts the picture's edge for a moment, which helps over the race and harms in a barn. A hold that does not outlast a cow's stay where cows stand packed. A way to leave pens beside the passage out of the picture. And photographs taken walk by walk: the application takes sixteen an hour at most, and a herd of ninety walks by in one.
- **The whole herd has to be confirmed, and the plain cows first of all.** With twelve of 89 cows confirmed, one unknown cow's picture in six passed as a confirmed cow in the cut-outs; with 67, one in 3,697. Plain cows are named less whatever is confirmed, and the stock detector finds them less often from above.
- **Two days of this farm are unseen**, and their footage has not been fetched. They are for a version that passes this validation first.

## Limits

- **One barn where it comes close, one pen where it does not, and a passage where it names who walks by.** Thirteen, sixteen and ninety Holstein cows, fixed cameras. In the first barn a cow is 220–320 pixels long in the analysed picture and seldom behind another; there the method named 72% of the animals by day and 50% at night. In the second she is 110–180 pixels long and lies between her neighbours; there it names 12% ([above](#a-second-farm)). A herd of 67 seen from the ceiling is told apart, and over a race the application named three in four of the cows that walked by, each for a second or two ([above](#a-third-farm)). Nothing here says how it does with another breed.
- **Most of the herd was enrolled.** Ten of thirteen. Every unknown animal is a chance of a wrong name, and the margin against strangers was measured with three. On the third farm, with twelve of 89 cows enrolled, one picture in six of the unknown cows passed as an enrolled cow.
- **Photographs from many occasions**, over several days, by day and by night and on every camera, which a farmer has to confirm: fifty of a cow from dozens of occasions name most animals, hundreds from one afternoon almost none ([above](#how-many-photographs-to-start)). The test used the publisher's crops, which are spread like that. The application now spreads its photographs over the hours, and a herd collected by it over days has not been tried.
- **A cow that is not found is not named.** Cows in the far row behind cubicle rails are missed even by the largest stock detector, and a box that touches the picture's edge is not used. On the first validation video that leaves two of ten enrolled cows unnamed for the whole video. In the second pen the detector finds a third of the cows that lie down, at any input size.
- **Night is harder.** Infrared light hides red-and-white patterns. At night the test named half of the animals, and the limit that kept unknown animals out did so by a small margin.
- **The limits were tested with a score that depends on how many photographs are confirmed.** They were set with two to three and a half thousand and held, narrowly, with four to six thousand. The score now used does not move with that number between 100 and 760 photographs a cow; with fewer than 100 it does, and nothing was measured beyond 760.
- **Names on animals the publisher did not box cannot be judged.** They are left out of the precision and counted in the conservative one.
- **Learning needs a GPU and time.** After every change to the confirmed photographs the networks are taught again, which takes ten minutes to half an hour on an Apple GPU, and no name is shown meanwhile. The largest stock detector and the four networks together take about half a second per picture there. A processor alone needs hours to learn and seconds per picture, and no other kind of GPU has been tried ([above](#a-processor-alone)).
- **Names on other rules' events were simulated.** No mounting video with known cows was available; see [above](#names-on-another-rules-events).
- **Weights.** The cattle starting weights were taught from datasets that forbid commercial use and are not published anywhere; the preset names an address that does not exist, so it cannot learn a herd as it stands. Without them the method names far fewer animals at night ([above](#the-cattle-starting-weights)). MIEWid is downloaded from its publisher, whose model card and repository state no licence.
- **Held out, not untouched, and now used.** Earlier work in this repository had scored another method on short windows of the test videos. The development figures for the second kind of network came from a trial script, not the application's code; the validation and test figures come from the application's code. Both test videos have now been seen by this method: a later version cannot be tested on them as on unseen video. Of the second farm two hours remain that no version has been shown, and of the third two days.

## Reproduce

Everything runs from the repository root in the detector's environment (`uv sync --extra default` in `detector/`). `$D` is the extracted dataset, `$M` the extracted MultiCamCows2024 and `$W` a work folder.

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

# The second farm, read over the network: photographs, one validation video, its score.
$python $herd/mmcows.py photographs $W/mmcows/photographs
$python $herd/mmcows.py frames mmcows-1200-cam1 $W/mmcows/frames/mmcows-1200-cam1 \
  --labels $W/mmcows/labels
$python $herd/mmcows.py run $W/mmcows/photographs/classification.json --video mmcows-1200-cam1 \
  --frames $W/mmcows/frames/mmcows-1200-cam1 --enrolled 1 2 3 5 6 7 9 10 11 13 14 15 \
  --preset config/detector/cow-identity.json --detector-weights yolo26x-seg.pt \
  --herd-weights cattle-without-mmcows.safetensors --animal-weights miewid-msv3.safetensors \
  --data $W/mmcows/data --output $W/mmcows/run-mmcows-1200-cam1.json
$python $herd/mmcows.py score $W/mmcows/run-mmcows-1200-cam1.json \
  --frames $W/mmcows/frames/mmcows-1200-cam1 --labels $W/mmcows/labels \
  --withheld 4 8 12 16 --output $herd/results/mmcows-validation-cam1.json

# A third farm, from the publisher's own cut-outs: a herd of 67 seen from the ceiling.
$python $herd/herd_size.py $M/MultiCamCows2024Root --cows 67 \
  --preset config/detector/cow-identity.json --herd-weights cattle-sideview.safetensors \
  --animal-weights miewid-msv3.safetensors --work $W/multicam/work-67 \
  --output $herd/results/multicam-herd-of-67.json

# The same farm's footage: fetch a day, place the publisher's pictures in it, cut the
# photographs, write a session's pictures and labels, run the application and score it.
$python $herd/multicam.py fetch $W/multicam/videos --days 2023Aug17
$python $herd/multicam_locate.py $M/MultiCamCows2024Root $W/multicam/videos --day 2023Aug17 \
  --camera 1 --output $W/multicam/located/2023Aug17-cam1.json
$python $herd/multicam_fill.py $W/multicam/located/2023Aug17-cam1.json $M/MultiCamCows2024Root \
  $W/multicam/videos --output $W/multicam/placed/2023Aug17-cam1.json
$python $herd/multicam.py photographs $W/multicam/placed/2023Aug1[456]-cam[12].json \
  --footage $W/multicam/videos --output $W/multicam/photographs
$python $herd/multicam.py frames multicam-17-cam1 $W/multicam/frames/multicam-17-cam1 \
  --footage $W/multicam/videos
$python $herd/multicam.py labels $W/multicam/frames/multicam-17-cam1 \
  --located $W/multicam/placed/2023Aug17-cam1.json --labels $W/multicam/labels
$python $herd/multicam.py run $W/multicam/photographs/classification.json --video multicam-17-cam1 \
  --frames $W/multicam/frames/multicam-17-cam1 --enrolled $(seq 1 89 | awk '$1 % 4') \
  --preset $herd/passage.json --detector-weights yolo26x-seg.pt \
  --herd-weights cattle-sideview.safetensors --animal-weights miewid-msv3.safetensors \
  --data $W/multicam/data --output $W/multicam/run-multicam-17-cam1.json
$python $herd/multicam.py score $W/multicam/run-multicam-17-cam1.json \
  --frames $W/multicam/frames/multicam-17-cam1 --labels $W/multicam/labels \
  --withheld $(seq 4 4 88) 90 --output $herd/results/multicam-validation-17-august-camera1.json
```

The cattle starting weights come from [`auxiliary.py`](herd/auxiliary.py), which gathers the other farms' photographs, and [`pretrain.py`](herd/pretrain.py). Development used [`app_track.py`](herd/app_track.py) and [`app_scores.py`](herd/app_scores.py) for the rotations (`--either-side`), [`tune.py`](herd/tune.py) for the rules, [`app_localization.py`](herd/app_localization.py) for the detectors and [`similarity_study.py`](herd/similarity_study.py) for the ways of scoring. [`app_smoke.py`](herd/app_smoke.py) starts the whole application on a short clip. [`parts.py`](herd/parts.py) and [`parts_compare.py`](herd/parts_compare.py) compare ways of building the herd model, and [`app_describe.py`](herd/app_describe.py) with [`rescore.py`](herd/rescore.py) score a finished run another way. [`event_names.py`](herd/event_names.py) simulates the names on another rule's events from a run that `app_run.py` wrote, and [`mounting_live.py`](herd/mounting_live.py) plays the mounting example to the whole application as a camera. For the second farm, [`app_limits.py`](herd/app_limits.py) replays a run at other limits, `mmcows.py postures` and `mmcows.py occasions` read the publisher's record of what each cow did, `mmcows.py angles` how steeply each camera looks down on her, [`mmcows_boxes.py`](herd/mmcows_boxes.py) asks the networks about the publisher's own boxes, and [`mmcows_outlines.py`](herd/mmcows_outlines.py) cuts the crops by the detector's boxes and outlines. For the third farm, `herd_size.py --per-walk` confirms fewer photographs of each walk, [`multicam_walks.py`](herd/multicam_walks.py) counts a run walk by walk, [`app_what_if.py`](herd/app_what_if.py) replays a run with a rule changed, and `app_localization.py` counts what a detector finds and how much of it could carry a name. The tests beside the scripts run with `pytest` in that folder.
