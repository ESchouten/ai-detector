"""One forward pass, with library ByteTrack applied only to whole animals."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from passage_runtime import sampled_frames

from aidetector.adapters.inference.device import mps_inference
from aidetector.adapters.inference.yolo import map_observations
from aidetector.domain.models import Frame


def observations(clip, source, protocol):
    from ultralytics import YOLO
    from ultralytics.trackers.byte_tracker import BYTETracker
    from ultralytics.utils import YAML
    from ultralytics.utils.checks import check_yaml

    settings = protocol["detector"]
    model = YOLO(settings["model"])
    names = {0: "whole_visible_cow", 1: "coat_torso"}
    if model.names != names:
        raise ValueError("Adapted detector class semantics differ from frozen protocol")
    tracker = BYTETracker(SimpleNamespace(**YAML.load(check_yaml(settings["tracker"]))))
    mapping = {key: (name, settings["confidence"]) for key, name in names.items()}
    stride = (
        clip["fps_numerator"] / clip["fps_denominator"] / protocol["processing_fps"]
    )
    if not stride.is_integer():
        raise ValueError("Processing cadence must divide native FPS")
    sampling = {
        **clip,
        "sampled_local_frame_indices": list(range(0, clip["frames"], int(stride))),
    }
    for index, image in sampled_frames(sampling, source, settings["frames_width"]):
        second = index * clip["fps_denominator"] / clip["fps_numerator"]
        at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=second)
        with mps_inference():
            result = model.predict(
                image,
                device="mps",
                conf=settings["confidence"],
                imgsz=settings["imgsz"],
                quantize=32,
                verbose=False,
            )[0]
            detected = map_observations(result, (Frame(at, image),), mapping)[0]
            raw = result.boxes.cpu().numpy()
        tracks = tracker.update(raw[raw.cls == 0], image)
        track_ids = {int(row[-1]): int(row[4]) for row in tracks}
        boxes = []
        whole_index = 0
        for box in detected.boxes:
            if box.label == "whole_visible_cow":
                box = replace(box, track_id=track_ids.get(whole_index))
                whole_index += 1
            boxes.append(box)
        yield index, second, replace(detected, boxes=tuple(boxes))
