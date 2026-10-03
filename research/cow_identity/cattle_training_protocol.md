# Bounded public-cattle adaptation cohort

Prepared on 2026-10-03, before training. The purpose is a controlled next
experiment if adaptation from a few same-farm enrollment images fails.
Production models and matching thresholds are unchanged.

A subsequent bounded CPU projection-head trial reused this frozen cohort and
selected its checkpoint only on its identity-disjoint validation split. Coverage
improved slightly there, but transfer to the harder adult-camera panels did not;
the head was not promoted. See the measured follow-up in
[BENCHMARK.md](BENCHMARK.md) and
[public-head.json](results/2026-10-03/recognition/public-head.json). The backbone
training plan below remains a proposed next experiment, not a completed result.

The cohort provides 3,033 training images from **219 identities**, with 53 different
identities reserved for validation. Every selected animal has 5–16 images from
different recording days. It combines top-down torso patterns and right-side
parlor views from different herds. This does not supply paired top/side views of
the same animal and does not establish robustness to all camera angles.

| Local source | Available identified crops | Selected training identities | Selected validation identities |
|---|---:|---:|---:|
| Cows2021, publisher `Identification/Test` | 8,670 / 181 IDs | 139 | 34 |
| SideViewCows2026, locally present parlor images | 10,683 / 105 IDs | 80 | 19 |
| OpenCows2020 | 4,240 train + 496 test / 46 IDs | Excluded | Excluded |

## Source and split decisions

The [Cows2021 paper](https://arxiv.org/html/2105.01938) distinguishes manually
identified still-image crops from anonymous training tracklets. We exclude all
23,350 local anonymous-tracklet images: tracklet labels are not globally unique
physical cow identities. The publisher's `Identification/Test` is **deliberately
repurposed as supervised training material**, with new identity-disjoint splits.
Any resulting model must not be advertised as an untouched Cows2021 test benchmark.
The local ZIP contains 181 identity directories with JPEGs, even though the paper
discusses 182 animals across its full identity study.

For [SideViewCows2026](https://zenodo.org/records/21605650), only locally available
parlor images are used. No barn/snapshot images were downloaded. The original
manifest provides consistent identity IDs and relative timestamps. We verify
image hashes against it, verify mask hashes against the publisher's `SHA256SUMS`,
and crop to each target's mask bounding box. We preserve the pixels inside that
box rather than paint the background away. Full masks are not required by the
training input. The publisher README grants CC-BY-4.0; source attribution remains
in the manifest.

[OpenCows2020](https://data.bris.ac.uk/data/dataset/10m32xl88x2b61zlkkgz3fml17)
provides random image splits and numbered crops without adequate capture-date
metadata for our grouping requirement. Its source imagery includes Bristol farm
data, so physical-animal overlap with Cows2021 is unresolved. A new namespace
alone would not prevent the same animal from becoming a false negative under two
labels. We therefore inventory but exclude OpenCows rather than invent a mapping.
Cows2021 and OpenCows use a Non-Commercial Government Licence; this preparation
is for the user's noncommercial research work, with no dataset redistribution.

All 8-calves and ETHZ samples and identities are excluded. MIEWid's foundation
training membership is not completely audited, so these are not claimed to be
animals unseen by its pretrained weights.

## Selection and validation

- Namespaces are `cows2021:<publisher ID>` and `sideview2026:<publisher ID>`.
- Require at least five observed days per animal; 14 sparse identities are excluded.
- Select up to 16 evenly spaced dates and one stable-hash-selected image per date.
  Date comes from the Cows2021 filename; SideView uses `floor(time_offset_s/86400)`.
  This is deliberately coarser than an encounter, keeping adjacent video frames
  out of separate roles.
- Within each dataset, sort identities by SHA-256 of `public-cattle-v1:<identity>`
  and reserve the first 20% (rounded down) for validation. Other identities train.
- For known validation animals, the earliest half of selected days forms the
  gallery and the later half the queries. Nine validation identities are never
  enrolled and supply unknown queries. Training/validation identities, recording
  groups, and identical pixel content cannot overlap.

This produces **318 validation gallery images and 427 validation queries**, over
44 known and nine unknown validation animals. Validation is within each source
farm, across days and unseen identities; it is not a new-farm claim. Selected
images contain no exact duplicate decoded pixels. That does not prove absence
of similar coat views, which is expected for the same animal.

Six identity montages were visually inspected after extraction: three top-down
Cows2021 animals and three SideView animals, four dates each. Coat consistency,
orientation, and mask crops look plausible; stall bars and partial occlusions
remain in the side views. This bounded check is not exhaustive relabeling.

## Proposed experiment, not yet executed

Reuse the existing MIEWid metric-training implementation. First freeze its early
backbone and adapt only the final block and embedding head, keeping the unadapted
model as the control. Use a bounded 200-step pilot, then a predeclared maximum of
600 steps only if validation improves. Select checkpoints using this cohort's
identity-disjoint validation, never ETHZ or 8-calves final windows.

Use batches of four identities and two images per identity from different days,
with two identities per dataset. This supplies both same-farm negatives and
cross-day positives instead of making all negatives trivially different scenes.
Existing supervised contrastive loss is adequate for this pilot; no new complex
training framework is needed.

Suggested augmentation: restrained brightness/contrast and scale/crop variation
that retains at least 80% of the torso, occasional grayscale, and mild rotations.
Top-down examples may additionally use quarter turns. Do not assume a mirrored
right flank is a true photograph of the animal's left flank. Keep a fixed native
440-pixel validation transform and cache each checkpoint's features under its
own fingerprint.

Report known rank-1, correct accepted coverage, incorrect-name accepts and unknown
false accepts together. Calibrate acceptance on the held-out validation cohort;
zero errors obtained by rejecting everything is not an improvement. Only after
locking a checkpoint and policy should the existing external-scene regression and
reserved video windows be evaluated. No experimental weights should become the
default merely because training loss decreases.

## Files and replay

`cattle_training_selection.jsonl` freezes every chosen source, identity, day,
role, and source/mask checksum. It contains metadata only. The exact generated
manifest is `.cache/cattle-public-training/manifest.json`; its hash and compact
counts are in `results/2026-10-03/cattle-training-cohort.json`. Extracted images
occupy approximately 653 MB in the ignored cache. No GPU or new dataset download
was needed.

```sh
detector/.venv/bin/python research/cow_identity/cattle_training_prepare.py \
  --selection research/cow_identity/cattle_training_selection.jsonl
detector/.venv/bin/python -m pytest -q research/cow_identity/test_cattle_training_prepare.py
```

Without `--selection`, the script deterministically creates a new cohort from
whatever eligible public images are present locally. That is a new manifest and
must not silently replace the frozen experiment. Every row exposes `identity`,
`dataset`, `day`, `group`, `split`, `validation_unknown`, `path`, `sha256`,
`pixels_sha256`, image dimensions, and its source provenance. Training reads only
rows with `split == "train"`; the other roles are evaluation-only.
