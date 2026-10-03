# Publisher geometry and the failed extended result

This is a diagnostic of already exposed data. The completed 2700–2999 panel
still fails its original precision gate at **97.8676%**. No labels, timestamps,
matching threshold or reported score have been changed. Source pixels at 3000
seconds and later remain closed.

## What the sources establish

The [publisher paper, sections 2–3](https://arxiv.org/html/2503.13777v2#S2),
describes YOLOv8m trained on manually boxed frames, followed by ByteTrack and
manual removal/correction of false positives and identity/track errors. It
acknowledges about 3,000 missing boxes and bias toward the detector family used
to generate labels. It does not document sparse-point interpolation, fixed
rectangle sizes, a visible-only versus amodal extent policy, or per-frame
instance masks. The exact annotation-generation and manual-edit implementation
is not published in the inspected benchmark tree. The paper's missing-box
estimate is not a certified bound on rectangle accuracy or identity errors.

The [dataset card](https://huggingface.co/datasets/tonyFang04/8-calves) identifies
normalized center-x/center-y/width/height columns. The pinned
[test-frame exporter](https://huggingface.co/datasets/tonyFang04/8-calves/blob/7394fdefc4aeafd530856b397623b8f833a86488/object_detector_benchmark/create_yolo_testset.py)
starts the first decoded frame at one; this agrees with our independently
verified `publisher_frame = video_index + 1`. Its separate
[MOT CSV helper](https://huggingface.co/datasets/tonyFang04/8-calves/blob/7394fdefc4aeafd530856b397623b8f833a86488/object_tracker_benchmark/get_gt_csv.py)
sets `top` from `y_max`, which is inconsistent with a top-left MOT rectangle.
Our pipeline never uses that CSV or helper: it converts the original normalized
centers directly, so that separate defect does not explain our scores.

## Numeric check, without inference or rescoring

[annotation_temporal_geometry.py](annotation_temporal_geometry.py) parses the
previously audited original numeric pickle buffers without executing pickle
instructions. It analyzes only frames 1–59981 (seconds 0–2999), and saves
[all statistics and all 34 error neighborhoods](results/2026-10-03/detection/annotation-temporal-geometry.json).
At a 0.001-pixel numerical tolerance, none of 476,053 consecutive-frame pairs
has a repeated complete rectangle, and none of 475,798 consecutive triples has
exactly linear complete center/size coordinates. Each calf has over 50,000
different widths in this interval. This rules out globally fixed boxes and
simple exact linear interpolation as explanations of these data. It does not
identify unpublished tracker smoothing or exclude isolated manual edits.

For cow 3 at 1840 seconds, width is 304.5 pixels; across the fixed ±1-second
neighborhood it varies from 178.8 to 304.5. For cow 1 at 1847, center-x ranges
from 540.0 to 582.5 pixels. These are changing, sometimes unstable rectangles,
not a single fixed body size. The two selected cow-4 errors at 2770 and 2790
have missing center-frame labels despite labels nearby. The complete error
review keeps those errors; adjacent labels are not interpolated into truth.

## What has already been tested

The previous **all-raw detector output** control changed the output collection:
it added unpaired raw proposals and omitted unpaired mask slots. Its diagnosis
found both worse rectangle geometry and assignment interference from extra
proposals. **Reciprocal union** retained slots but expanded their rectangles.
Earlier controls also tried coordinate means and fixed padding. All are
preserved, including failures. Their code does not implement exact reciprocal
raw-coordinate substitution while retaining every original slot, order and
name. That is a distinct, narrowly scoped CPU control; it must run on all five
exposed panels, not just these 34 errors, before any recommendation.

None of these observations establishes biological correctness of every emitted
name. Publisher-label uncertainty and genuine partial/merged/duplicate masks
both remain possible. Independent farmer/video validation is still required.
