"""Read-only diagnosis of every named error in the completed reserved trial."""

import argparse
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_actual_audit import error_rows
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components
from detection_errors import overlaps
from video_assessment import annotations, pair_boxes, pixels_hash, read_frame, truth_at

from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/detection"
RUN = Path(".cache/cow-cutie/streaming-reserved")
PROTOCOL = ROOT / "detection_reserved_audit_protocol_v2.json"
OUTPUT = RESULTS / "cutie-reserved-error-audit.json"
IMAGES = Path(".cache/cow-cutie/reserved-error-audit")
FILES = {
    "streaming": RUN / "streaming.json",
    "clip": Path(".cache/cow-cutie/reserved-2fps-clip/sampled.json"),
    "strict_report": RESULTS / "cutie-streaming-reserved.json",
    "prefix_parity": RESULTS / "cutie-reserved-prefix-parity.json",
    "evaluation": ROOT / "detection_reserved_evaluation.json",
    "video": Path("datasets/8-calves/video/pmfeed_4_3_16.mp4"),
    "annotations": Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
    "source_pickle": Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
}
HELPERS = (
    "detection_actual_audit.py",
    "detection_cutie.py",
    "detection_cutie_variants.py",
    "detection_errors.py",
    "video_assessment.py",
    "detection_assessment.py",
)


def freeze():
    if PROTOCOL.exists():
        raise ValueError("Preserve the completed audit freeze")
    paths = [Path(__file__), *(ROOT / name for name in HELPERS)]
    write_json(
        PROTOCOL,
        {
            "scope": "Diagnosis after a failed reserved evaluation; no rescoring, selection, threshold change or exclusion of errors",
            "windows": [[1800, 2099], [2700, 2999]],
            "closed_seconds": "3000 to end; no decoding or annotation inspection",
            "selection": "Every emitted name that fails the original one-to-one IoU>=.5 truth assignment; assert original strict count before diagnosis",
            "diagnostics": "Original indexed mask, largest component, paired current raw YOLO proposal and unchanged publisher annotations; geometry comparisons are not alternative accuracy estimates",
            "files": {
                key: {"path": str(path), "sha256": digest(path)}
                for key, path in FILES.items()
            },
            "implementation": {str(path): digest(path) for path in paths},
            "libraries": {"opencv": cv2.__version__, "numpy": np.__version__},
        },
    )


def inputs():
    frozen = json.loads(PROTOCOL.read_text())
    paths = {
        item["path"]: item["sha256"] for item in frozen["files"].values()
    } | frozen["implementation"]
    if any(digest(Path(path)) != expected for path, expected in paths.items()):
        raise ValueError("A frozen audit input changed")
    if frozen["libraries"] != {"opencv": cv2.__version__, "numpy": np.__version__}:
        raise ValueError("Audit geometry dependencies changed")
    data = {
        key: json.loads(path.read_text())
        for key, path in FILES.items()
        if path.suffix == ".json"
    }
    records, _ = annotations(SimpleNamespace(**FILES))
    return frozen, data, records


def checked_mask(frame, shape):
    path = RUN / "masks" / f"{frame['second']}.png"
    if digest(path) != frame["mask_sha256"]:
        raise ValueError("Indexed mask differs from the recorded inference")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if mask.dtype != np.uint8 or mask.shape != shape:
        raise ValueError("Indexed mask geometry changed")
    cleaned, statistics = largest_components(mask)
    keys = ("x1", "y1", "x2", "y2", "track_id")

    def geometry(rows):
        return [tuple(row[key] for key in keys) for row in rows]

    if geometry(boxes_from_mask(cleaned)) != geometry(frame["boxes"]):
        raise ValueError("Largest components do not reproduce emitted geometry")
    return mask, statistics


def diagnose(error, frame, records, clip):
    truth = truth_at(records, frame["publisher_frame"], clip["width"], clip["height"])
    boxes = [BoundingBox(**row) for row in frame["boxes"]]
    paired = pair_boxes(boxes, truth)
    slot = error["seed"] - 1
    partner = next(row for row in frame["reciprocal_pairs"] if row["track_id"] == slot)
    proposal = frame["raw_detector_boxes"][partner["proposal_index"]]
    values = overlaps(BoundingBox(**proposal), truth)
    mask, components = checked_mask(frame, (clip["height"], clip["width"]))
    raw_box = next(row for row in boxes_from_mask(mask) if row["track_id"] == slot)
    return {
        **error,
        "publisher_frame": frame["publisher_frame"],
        "source_pixels_sha256": frame["source_pixels_sha256"],
        "mask_sha256": frame["mask_sha256"],
        "probabilities": next(
            row for row in frame["objects"] if row["track_id"] == slot
        ),
        "components": next(row for row in components if row["track_id"] == slot),
        "original_mask_box": raw_box,
        "proposal_index": partner["proposal_index"],
        "proposal": proposal,
        "proposal_own_overlap": next(
            (row for row in values if row["cow"] == error["seed"]), None
        ),
        "proposal_all_overlaps": values,
        "own_truth_assigned_to_track": next(
            (
                boxes[index].track_id
                for index, target in paired.items()
                if truth[target]["cow"] == error["seed"]
            ),
            None,
        ),
        "truth": truth,
    }, mask


def rectangle(image, box, color, text):
    points = [int(value) for value in box]
    cv2.rectangle(image, tuple(points[:2]), tuple(points[2:]), color, 2)
    cv2.putText(
        image,
        text,
        (points[0], max(14, points[1] - 4)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        color,
        1,
        cv2.LINE_AA,
    )


def render(capture, row, mask, fps, index):
    frame_id, source = read_frame(capture, row["second"], fps)
    if (
        frame_id != row["publisher_frame"]
        or pixels_hash(source) != row["source_pixels_sha256"]
    ):
        raise ValueError("Review pixels differ from inference")
    image = source.copy()
    foreground = mask == row["seed"]
    image[foreground] = (
        image[foreground] * 0.75 + np.array([0, 128, 255]) * 0.25
    ).astype(np.uint8)
    for item in row["truth"]:
        color = (0, 255, 0) if item["cow"] == row["seed"] else (170, 170, 170)
        rectangle(image, item["box"], color, f"GT {item['cow']}")
    proposal = row["proposal"]
    rectangle(
        image,
        [proposal[key] for key in ("x1", "y1", "x2", "y2")],
        (255, 255, 0),
        "YOLO",
    )
    rectangle(image, row["box"], (0, 0, 255), f"Named {row['seed']}")
    canvas = cv2.copyMakeBorder(
        image, 55, 0, 0, 0, cv2.BORDER_CONSTANT, value=(245, 245, 245)
    )
    own = row["own_overlap"]["iou"] if row["own_overlap"] else None
    detector = (
        row["proposal_own_overlap"]["iou"] if row["proposal_own_overlap"] else None
    )
    lines = [
        f"#{index:02d} t={row['second']} name={row['seed']} | own IoU LCC={own} YOLO={detector}",
        "Red: emitted LCC | Cyan: corroborating YOLO | Green: own GT | Orange: original mask",
    ]
    for y, line in zip((20, 43), lines, strict=True):
        cv2.putText(
            canvas,
            line,
            (8, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )
    path = IMAGES / f"{index:02d}-{row['second']}-cow-{row['seed']}.jpg"
    if not cv2.imwrite(str(path), canvas):
        raise ValueError("Could not write review image")
    return {"path": str(path), "sha256": digest(path)}


def contact_sheets(images):
    sheets = []
    for offset in range(0, len(images), 6):
        page = np.full((3 * 655, 2 * 800, 3), 245, np.uint8)
        for index, source in enumerate(images[offset : offset + 6]):
            image = cv2.imread(source["path"])
            y, x = divmod(index, 2)
            page[y * 655 : (y + 1) * 655, x * 800 : (x + 1) * 800] = image
        path = IMAGES / f"sheet-{offset // 6 + 1}.jpg"
        if not cv2.imwrite(str(path), page):
            raise ValueError("Could not write contact sheet")
        sheets.append({"path": str(path), "sha256": digest(path)})
    return sheets


def run():
    frozen, data, records = inputs()
    value, clip = data["streaming"], data["clip"]
    errors = error_rows(
        value,
        records,
        clip,
        data["evaluation"],
        lambda frame, box: box.track_id in frame["named_track_ids"],
        frozen["windows"],
    )
    counts = Counter(
        str(start)
        for row in errors
        for start, end in frozen["windows"]
        if start <= row["second"] <= end
    )
    expected = {
        key: row["naming_counts"]["unmatched_named"]
        for key, row in data["strict_report"]["conditions"].items()
    }
    if dict(counts) != expected or any(
        row["assigned_cow"] is not None for row in errors
    ):
        raise ValueError("Error selection differs from immutable strict report")
    frames = {row["second"]: row for row in value["timeline"]}
    IMAGES.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(FILES["video"]))
    rows, images = [], []
    try:
        for index, error in enumerate(errors, start=1):
            row, mask = diagnose(error, frames[error["second"]], records, clip)
            images.append(render(capture, row, mask, clip["source_fps"], index))
            rows.append(row)
    finally:
        capture.release()
    report = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(PROTOCOL),
        "strict_report_sha256": digest(FILES["strict_report"]),
        "counts_by_window": dict(counts),
        "counts_by_named_cow": dict(Counter(str(row["seed"]) for row in rows)),
        "errors": rows,
        "images": images,
        "contact_sheets": contact_sheets(images),
        "all_errors_remain_counted": True,
    }
    write_json(OUTPUT, report)
    print(
        json.dumps(
            {key: report[key] for key in ("counts_by_window", "counts_by_named_cow")}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    args = parser.parse_args()
    freeze() if args.action == "freeze" else run()
