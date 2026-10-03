# Visible ear numbers as an additional identity source

Product requirement: build identities gradually without requiring the farmer to
name cows or enroll photographs. Start with anonymous observations, accumulate
useful views through demonstrated continuity, and attach an ear number when its
reading and ownership are reliable. Manual correction is optional. This replaces
the earlier plan to require confirmation of each initial name; it is not a claim
that automatic enrollment already works.

A local text reader complements appearance and continuous tracking. Reading
text, interpreting its meaning and associating it with one animal are three
separate tasks. An anonymous camera track is evidence about a possible animal,
not yet proof of a permanent biological identity across visits.

## Evidence and current limits

[ReadMyCow, WACV 2024](https://openaccess.thecvf.com/content/WACV2024/html/Smink_Computer_Vision_on_the_Edge_Individual_Cattle_Identification_in_Real-Time_WACV_2024_paper.html)
combines tag detection, tracking and a scene-text recognizer. It selects useful
readings over time and reports 96.1% accuracy for printed tags in its field
evaluation. That result does not establish our 99% precision target, performance
on distant overhead footage or reliable transfer of a tag identity onto another
camera's cow track. Its dataset is not publicly downloadable according to the
paper; a smaller subset can be requested from the authors. No request has been
sent.

[Gao et al., Sensors 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11014036/)
publish detection and recognition datasets, including multiline printed and
handwritten tags. Their recognition set was selected for readability; the paper
describes retaining 3,238 of 9,705 detected crops and filtering very small,
blurred or obscured tags. Therefore recognition accuracy on these crops is
conditional, not an estimate of how many cows a normal camera can identify.
The public archive actually contains 3,204 image/label pairs; preserve this
difference in the local inventory. Its roughly 28 MB size permits a cheap
experiment. A fixed, label-blind 32-image subset of the separate detection set
was fetched individually (roughly 94 MB), avoiding its roughly 8 GB archive.
Three selected images have no published labels and remain explicitly unannotated.
These still images contain no certified animal identities or temporal tracks.

The existing 800×600 crowded-calves starting image has no clearly readable
ear-number text on visual inspection. That observation applies to the inspected
frame, not every future frame or all farm cameras. OCR cannot recover digits
that the source pixels do not resolve. No later reserved video was inspected
for this decision.

## Bounded first experiment

Use an existing OCR library and its published models. The isolated research
environment uses RapidOCR 3.9.2 and ONNX Runtime 1.30.0 on CPU with bounded
threads. The application environment and dependency lock remain unchanged.
RapidOCR provides text localization and recognition rather than requiring us
to write a new OCR stack. Its [official implementation](https://github.com/RapidAI/RapidOCR)
supports local inference; no farm image needs uploading to a service.

Before reading model outputs, inventory original polygons and literal strings,
group shared plausible number strings and duplicate/near-duplicate images, and
freeze development and reserved groups. Preserve leading zeros, multiline text,
dates and nonnumeric symbols. Ambiguous tag layouts must stay ambiguous; a
short farm number and a national registration number are not interchangeable.
Evaluate full-line transcription, text localization, rejection and latency
separately. No nearest-roster correction or label-derived prompt is permitted.
Cache raw OCR results keyed by input pixels, model hashes and settings.

This first crop experiment cannot validate tag detection in whole camera frames,
video agreement, ownership by a cow or identity across cameras. Those require
their own footage and tests before enabling automatic names.

The first fixed 64-image development run confirms that generic OCR confidence
cannot serve as identity confidence. At the preselected 0.95 score gate,
65 of 82 emitted lines were exact and 86 of 157 annotated lines were missed;
only nine complete tags were exact. Supplying the original line polygons to
the same recognizer improved conditional precision to 104 of 113 readings,
still with nine high-score wrong readings. Both text localization and reading
need improvement. These are all-line transcription counts, not correctly
identified animals; dates and other text remain in the denominators.
The larger PP-OCRv6-medium detector/reader was also worse on the same fixed
development panel: 60 of 79 accepted lines were exact, versus 65 of 82 for the
small model, while total CPU time rose from 12.42 to 60.45 seconds. See the
[OCR baseline record](EAR_TAG_OCR_BASELINE.md); no model or threshold is promoted.

## Dutch number and barcode checks

The Ministry's [June 2012 reading guide](https://www.veehandel.nu/archief/Runder%20Oormerken%20Nederland%20Juni%202012.pdf)
distinguishes the complete nine-digit number from its shorter work number and
documents a weighted check digit. Its Code 128 and older ITF barcode layouts
encode a leading zero followed by the complete number. The research-only
`eartag_numbers.py` implements that specific check without correcting digits,
guessing a country or accepting a partial number. It rejects every single-digit
substitution in the published test example; compensating multiple errors can
still pass. A valid checksum is not proof of a correct reading or animal owner.

The [NVWA's more recent identification document](https://www.nvwa.nl/site/binaries/site-content/collections/documents/veterinair/ks-documenten/werkvoorschriften-veterinair-algemeen/htsl-rnd-ir-id01-informatiedocument-identificatie-en-registratie-runderen/HTSL-RND-IR-ID01%2BIdentificatie%2Ben%2Bregistratie%2BRund%2Bv01.pdf)
also describes twelve-digit Dutch numbers. Those remain explicitly unsupported
by this nine-digit research parser; it must not truncate or reinterpret them.

An isolated [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp/tree/master/wrappers/python)
3.1.1 smoke decoded 16 generated Code 128/ITF cases, including rotation, and
rejected blank pixels. Tests separate a valid barcode from a valid cattle-number
checksum and require independent country evidence. The
[recorded result](results/2026-10-03/ear-tags/barcode-sdk-smoke.json) establishes
the library integration only. No actual farm-tag barcode accuracy or camera
distance has been measured, and no barcode dependency was added to the app.

## Intended automatic flow and acceptance requirements

- The farmer selects cameras and enables the detector. The system collects a
  bounded set of diverse, clear views of anonymous animals automatically. It
  must continue learning without an ever-growing queue requiring manual review.
- Keep separate the observed track, a proposed association across visits, and a
  number-backed animal identity. A camera restart or reused tracker slot cannot
  merge these records. Appearance guesses must not become their own training
  labels; new reference images need independently established continuity or
  number evidence, with their original provenance retained.
- Read tags from source-resolution pixels. Preserve the literal number and its
  scheme; dates, herd prefixes, partial digits and farm numbers are not silently
  interchangeable. Readability determines whether a reading is possible, not
  whether a cow exists. Unreadable animals remain in the coverage denominator.
- Automatically attach a number only after calibrated reading acceptance and
  unambiguous same-frame tag-to-animal ownership. Independent chronological
  observations can strengthen evidence; repeated frames and repeated cached
  OCR results cannot. Agreement alone does not eliminate systematic mistakes.
- On a later view, appearance can suggest a match to an accumulated profile.
  It must meet the same precision and unknown-animal rejection requirements as
  the original recognition goal. Two simultaneous animals cannot receive one
  identity. A single high similarity must not permanently join two profiles.
- Keep the exact tag crop, its source frame and associated animal evidence so a
  wrong association can be inspected and undone. Conflicting readings suspend
  automatic naming and enrollment for that association; they do not silently
  overwrite a previous number or contaminate every linked reference photograph.
- Show learning animals and established numbers in the existing Herd screen.
  Correction remains available, but entering a name, confirming a photograph or
  supplying a herd roster is not required for normal operation.
- A clear reading can seed a continuously tracked instance in the same view.
  A separate reading camera needs a demonstrated handoff; matching timestamps
  alone does not identify a cow on an overview camera.
- Reading should be sparse and cached. It must not delay camera capture or
  detector processing. Additional recognition models are optional and loaded
  only for a configured reader.

Acceptance needs an actual chronological trial from an empty catalog: no
ground-truth seed names, no hand-selected enrollment photos and no human action
between startup and scoring. Measure automatic grouping purity, duplicate
profiles per animal, wrong merges, number transcription, tag ownership, time to
first reliable number, naming coverage and false naming of new animals.
Development controls with correctly supplied initial names remain useful for
isolating tracking faults, but cannot satisfy this requirement. The unchanged
99% naming precision, 60% correct naming coverage and 1% maximum false naming of
withheld unknowns still apply to the completed system. A public cropped-tag OCR
score does not substitute for that end-to-end test.

Status: development baselines and integration checks, with automatic enrollment
still under development. No OCR assignment is enabled in the application and
no end-to-end animal identity accuracy has been established by these tag tests.
