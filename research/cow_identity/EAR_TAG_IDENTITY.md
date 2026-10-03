# Visible ear numbers as an additional identity source

Decision: investigate an optional local text reader alongside appearance and
continuous tracking. Do not replace uncertain appearance names with uncertain
text. A visible number is potentially a much stronger enrollment anchor, but
reading text, interpreting its meaning and associating it with one animal are
three separate tasks.

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
experiment; the separate roughly 8 GB detection archive is not needed yet.

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

## Intended farmer flow and acceptance requirements

- Keep the existing Herd as the source of confirmed cows. A number remains a
  string, with its identifier scheme explicit where needed. A nonunique partial
  number cannot silently select a cow.
- When a sufficiently clear tag is visible, show its exact crop beside the
  proposed number and cow. A farmer can confirm it through the same exact-photo
  workflow as other live naming; there is no separate configuration wizard.
- Automatic assignment, if later validated, requires consistent independent
  frames, unambiguous same-frame ownership and the existing strict precision
  target. Repeated copies of one frame are not independent evidence. Agreement
  alone does not eliminate systematic OCR mistakes.
- Text outside the animal, conflicting numbers, uncertain ownership, source
  reconnection and stale snapshots cannot change a live identity. No OCR reading
  silently overwrites a human confirmation or enrolls reference photographs.
- A clear reading can seed a continuously tracked instance in the same view.
  A separate reading camera needs a demonstrated handoff; matching timestamps
  alone does not identify a cow on an overview camera.
- Reading should be sparse and cached. It must not delay camera capture or
  detector processing. Additional recognition models are optional and loaded
  only for a configured reader.

Status: research and dataset preparation. No OCR assignment is enabled in the
application, and no accuracy claim has yet been measured locally.
