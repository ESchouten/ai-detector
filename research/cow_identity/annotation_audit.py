"""Independently inspect the pinned 8-calves annotations without unpickling.

Only this reviewed artifact's protocol-5 numeric buffer layout is supported.
Pickle opcodes are parsed as data; no GLOBAL, REDUCE or BUILD is executed.
The development-frame figures compare publisher boxes with actual YOLO output.
"""

import argparse
import hashlib
import json
import pickletools
from pathlib import Path

import cv2
import numpy as np

PUBLISHER_SHA256 = "2c5dbf9c7856bfb15fe38b99487ff576f1b281fcf70af84cc0ac982af1ef203e"
VIDEO_SHA256 = "475824794af23d28d9d92039eb893d73ab0374c8b3272d42c176b5f363cd9825"
ROW_COUNT = 537910
COLUMN_NAMES = ("class", "x", "y", "w", "h", "conf", "tracklet_id", "frame_id")
SECONDS = (0, 1, 10, 330, 331, 340, 930, 931, 940)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publisher_arrays(path):
    """Extract the independently audited raw ndarray buffers, never a DataFrame."""
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != PUBLISHER_SHA256:
        raise ValueError("Only the reviewed publisher annotation hash is supported")
    operations = list(pickletools.genops(data))
    columns = tuple(operations[index][1] for index in range(273, 289, 2))
    if columns != COLUMN_NAMES:
        raise ValueError("Publisher columns differ from the audited buffer layout")
    buffers = [arg for op, arg, _ in operations if op.name == "BYTEARRAY8"]
    if [len(block) for block in buffers] != [
        ROW_COUNT * 8 * n for n in (1, 5, 1, 1, 1)
    ]:
        raise ValueError("Publisher numeric buffers differ from the audited layout")
    numeric = np.frombuffer(buffers[1], dtype="<f8").reshape(5, ROW_COUNT)
    return {
        "class": np.frombuffer(buffers[0], dtype="<i8"),
        **dict(
            zip(
                ("x_center", "y_center", "width", "height", "confidence"),
                numeric,
                strict=True,
            )
        ),
        "cow_id": np.frombuffer(buffers[2], dtype="<i8"),
        "frame_id": np.frombuffer(buffers[3], dtype="<i8"),
    }


def compare_conversion(original, path):
    order = np.lexsort((original["cow_id"], original["frame_id"]))
    result = {}
    with np.load(path, allow_pickle=False) as converted:
        for key in ("cow_id", "frame_id", "x_center", "y_center", "width", "height"):
            expected = original[key][order].astype(converted[key].dtype)
            result[key] = bool(np.array_equal(expected, converted[key]))
    return result


def boxes_at(records, frame_id, width, height):
    selected = records["frame_id"] == frame_id
    centers = np.column_stack(
        (records["x_center"][selected], records["y_center"][selected])
    )
    sizes = np.column_stack((records["width"][selected], records["height"][selected]))
    bounds = np.column_stack((centers - sizes / 2, centers + sizes / 2))
    bounds *= (width, height, width, height)
    bounds = bounds.clip(0, (width, height, width, height)).astype(int)
    return records["cow_id"][selected], bounds


def annotated_panel(image, boxes, captions, heading, color):
    panel = cv2.copyMakeBorder(
        image, 40, 0, 0, 0, cv2.BORDER_CONSTANT, value=(245, 245, 245)
    )
    cv2.putText(
        panel, heading, (12, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (30, 30, 30), 2
    )
    for (x1, y1, x2, y2), caption in zip(boxes, captions, strict=True):
        cv2.rectangle(panel, (x1, y1 + 40), (x2, y2 + 40), color, 2)
        cv2.putText(
            panel,
            caption,
            (x1, max(16, y1 + 36)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            4,
        )
        cv2.putText(
            panel,
            caption,
            (x1, max(16, y1 + 36)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
        )
    return panel


def overlap_scores(predicted, truth):
    if not len(predicted):
        return [0.0] * len(truth)
    intersection = np.maximum(
        0,
        np.minimum(truth[:, None, 2:], predicted[None, :, 2:])
        - np.maximum(truth[:, None, :2], predicted[None, :, :2]),
    ).prod(axis=2)
    truth_area = (truth[:, 2:] - truth[:, :2]).prod(axis=1)
    predicted_area = (predicted[:, 2:] - predicted[:, :2]).prod(axis=1)
    return (
        (intersection / (truth_area[:, None] + predicted_area[None, :] - intersection))
        .max(axis=1)
        .tolist()
    )


def run(args):
    from ultralytics import YOLO

    records = publisher_arrays(args.publisher)
    conversion = compare_conversion(records, args.converted)
    if not all(conversion.values()):
        raise ValueError(f"Independent conversion disagrees with NPZ: {conversion}")
    if digest(args.video) != VIDEO_SHA256:
        raise ValueError("Video differs from the previously assessed publisher file")
    if not args.detector.is_file():
        raise ValueError(
            "Supply existing detector weights; this audit does not download models"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(args.detector))
    cow_classes = [key for key, name in model.names.items() if name == "cow"]
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    video = {
        "fps": fps,
        "frames": int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    panels = []
    try:
        for second in SECONDS:
            zero_index = round(second * fps)
            capture.set(cv2.CAP_PROP_POS_FRAMES, zero_index)
            ok, image = capture.read()
            if not ok:
                raise ValueError(f"Cannot decode development frame {zero_index}")
            ids, truth = boxes_at(
                records, zero_index + 1, video["width"], video["height"]
            )
            result = model.predict(
                image,
                device=args.device,
                imgsz=640,
                conf=0.25,
                classes=cow_classes,
                quantize=32,
                verbose=False,
            )[0]
            predicted = result.boxes.xyxy.cpu().numpy()
            confidences = result.boxes.conf.cpu().numpy()
            left = annotated_panel(
                image,
                truth,
                [f"GT {cow}" for cow in ids],
                f"{second}s / publisher frame {zero_index + 1}: original labels",
                (0, 230, 0),
            )
            right = annotated_panel(
                image,
                predicted.astype(int),
                [f"YOLO {score:.2f}" for score in confidences],
                "Actual YOLO26m-seg / 640px / confidence >= 0.25",
                (0, 190, 255),
            )
            filename = f"development-{second:04d}s.jpg"
            if not cv2.imwrite(
                str(args.output / filename), np.concatenate((left, right), axis=1)
            ):
                raise OSError(f"Cannot write audit panel {filename}")
            panels.append(
                {
                    "second": second,
                    "video_zero_index": zero_index,
                    "publisher_frame": zero_index + 1,
                    "decoded_next_index": capture.get(cv2.CAP_PROP_POS_FRAMES),
                    "ids": ids.tolist(),
                    "truth_boxes": truth.tolist(),
                    "predicted_boxes": predicted.tolist(),
                    "best_iou_per_truth": overlap_scores(predicted, truth),
                    "figure": filename,
                }
            )
    finally:
        capture.release()
    summary = {
        "publisher_sha256": PUBLISHER_SHA256,
        "video_sha256": VIDEO_SHA256,
        "converted_sha256": digest(args.converted),
        "detector_sha256": digest(args.detector),
        "reader": "pickletools opcode parsing; five pinned BYTEARRAY8 buffers; no pickle execution",
        "row_count": ROW_COUNT,
        "column_names": COLUMN_NAMES,
        "npz_matches_publisher_after_sort_and_dtype_cast": conversion,
        "coordinate_convention": "normalized-center-width-height",
        "video": video,
        "label_frame_range": [
            int(records["frame_id"].min()),
            int(records["frame_id"].max()),
        ],
        "device": args.device,
        "precision": "FP32",
        "panels": panels,
        "limits": "Nine development frames only; no held-out-region inspection; single-image predict localization diagnostic, not tracking or recognition score",
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {"conversion": conversion, "video": video, "figures": len(panels)}, indent=2
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publisher",
        type=Path,
        default=Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
    )
    parser.add_argument(
        "--converted",
        type=Path,
        default=Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
    )
    parser.add_argument(
        "--video", type=Path, default=Path("datasets/8-calves/video/pmfeed_4_3_16.mp4")
    )
    parser.add_argument(
        "--detector", type=Path, default=Path("detector/yolo26m-seg.pt")
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/cow-identity/annotation-audit")
    )
    parser.add_argument("--device", default="cpu")
    run(parser.parse_args())
