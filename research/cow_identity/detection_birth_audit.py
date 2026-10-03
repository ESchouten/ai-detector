"""Independent count parity and fixed first-error diagnosis; no alternative score."""

import argparse
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_actual_audit import overlaps
from video_assessment import annotations, pair_boxes, pixels_hash, read_frame, truth_at

from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/detection"
RUN = Path(".cache/cow-cutie/crowded-births")
OUTPUT = Path(".cache/cow-cutie/crowded-birth-audit")
SELECTION = RESULTS / "crowded-births-audit-selection.json"
WINDOWS = ((330, 629), (930, 1229), (1230, 1529))
ERRORS = ("wrong_name", "unknown_named", "unmatched_named")
FILES = {
    "protocol": ROOT / "detection_birth_protocol.json",
    "streaming": RUN / "streaming.json",
    "report": RESULTS / "crowded-births.json",
    "six_seed_baseline": RESULTS / "uninitialized-unknown.json",
    "eight_seed_baseline": RESULTS / "cutie-streaming-development.json",
    "clip": Path(".cache/cow-cutie/calibration-clip/sampled.json"),
    "video": Path("datasets/8-calves/video/pmfeed_4_3_16.mp4"),
    "annotations": Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
    "source_pickle": Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
    "seed_masks": Path(".cache/cow-cutie/uninitialized-seeds/0-masks.npz"),
    "seed_manifest": Path(".cache/cow-cutie/uninitialized-seeds/manifest.json"),
}


def classified(name, actual):
    if actual is None:
        return "unmatched_named"
    if actual not in range(1, 7):
        return "unknown_named"
    return "correct_name" if name == actual else "wrong_name"


def panel_counts(value, records, window):
    counts = Counter({key: 0 for key in ("correct_name", *ERRORS)})
    selected = {key: None for key in ERRORS}
    seeds = value["provenance"]["seed_prompts"]
    for frame in value["timeline"]:
        if not window[0] <= frame["second"] <= window[1]:
            continue
        truth = truth_at(records, frame["publisher_frame"], 800, 600)
        counts.update(
            frames=1,
            visible_annotations=len(truth),
            visible_known=sum(row["cow"] in range(1, 7) for row in truth),
            visible_unknown=sum(row["cow"] not in range(1, 7) for row in truth),
        )
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        pairs = pair_boxes(boxes, truth)
        for index, box in sorted(enumerate(boxes), key=lambda pair: pair[1].track_id):
            if box.track_id not in frame["named_track_ids"]:
                continue
            named = seeds[box.track_id]["cow"]
            actual = truth[pairs[index]]["cow"] if index in pairs else None
            outcome = classified(named, actual)
            counts[outcome] += 1
            if outcome in ERRORS and selected[outcome] is None:
                selected[outcome] = {
                    "second": frame["second"],
                    "named_cow": named,
                    "assigned_cow": actual,
                    "outcome": outcome,
                    "track_id": box.track_id,
                    "box": [box.x1, box.y1, box.x2, box.y2],
                    "all_overlaps": overlaps(box, truth),
                    "truth": truth,
                    "mask_sha256": frame["mask_sha256"],
                    "source_pixels_sha256": frame["source_pixels_sha256"],
                }
    return dict(counts), selected


def select():
    if SELECTION.exists():
        raise ValueError("Preserve the original pre-image selection")
    data = {
        k: json.loads(p.read_text()) for k, p in FILES.items() if p.suffix == ".json"
    }
    value, report = data["streaming"], data["report"]
    if not value["complete"] or report["status"] != "COMPLETE_EXPOSED_CONTROL":
        raise ValueError("Only a complete frozen control can be compared")
    if value["provenance"]["protocol_sha256"] != digest(FILES["protocol"]):
        raise ValueError("Execution protocol differs")
    if [f["second"] for f in value["timeline"]] != list(range(1530)):
        raise ValueError("Complete integer chronology is required")
    records, _ = annotations(SimpleNamespace(**FILES))
    panels = {}
    for window in WINDOWS:
        counts, selected = panel_counts(value, records, window)
        if any(
            counts[k] != report["conditions"][str(window[0])]["naming_counts"][k]
            for k in counts
        ):
            raise ValueError("Independent count parity failed")
        comparisons = {}
        for key in ("six_seed_baseline", "eight_seed_baseline"):
            other = data[key]["conditions"][str(window[0])]
            for column in (
                "frames",
                "visible_annotations",
                "visible_known",
                "visible_unknown",
            ):
                if counts[column] != other["naming_counts"][column]:
                    raise ValueError("Baseline truth denominator changed")
            comparisons[key] = {
                key: other[key]
                for key in ("naming_counts", "known_coverage", "conservative_precision")
            }
        panels[str(window[0])] = {
            "independent_counts": counts,
            "first_errors": selected,
            "comparisons": comparisons,
        }
    write_json(
        SELECTION,
        {
            "scope": "Post-result diagnostic. First chronological error of each named type per original panel; tie uses smallest stable track ID. Absent error categories remain null. Freeze before error pixels or masks are viewed. No alternate score or retuning.",
            "files": {str(path): digest(path) for path in FILES.values()},
            "implementation_sha256": digest(Path(__file__)),
            "panels": panels,
            "all_original_truth_counts_equal": True,
        },
    )
    print(json.dumps({k: v["first_errors"] for k, v in panels.items()}))


def rectangle(image, bounds, color, label):
    points = [int(x) for x in bounds]
    cv2.rectangle(image, tuple(points[:2]), tuple(points[2:]), color, 2)
    cv2.putText(
        image,
        label,
        (points[0], max(15, points[1] - 4)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        color,
        1,
        cv2.LINE_AA,
    )


def render_case(capture, row, frame):
    _, image = read_frame(capture, row["second"], 20)
    if pixels_hash(image) != row["source_pixels_sha256"]:
        raise ValueError("Review source pixels differ")
    path = RUN / "masks" / f"{row['second']:g}.png"
    if digest(path) != row["mask_sha256"]:
        raise ValueError("Review mask changed")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    truth, prediction, raw = image.copy(), image.copy(), image.copy()
    for item in row["truth"]:
        rectangle(truth, item["box"], (0, 255, 0), f"Publisher {item['cow']}")
    occupied = mask == row["track_id"] + 1
    prediction[occupied] = (
        prediction[occupied] * 0.65 + np.array([0, 140, 255]) * 0.35
    ).astype(np.uint8)
    for box in frame["boxes"]:
        rectangle(
            prediction,
            [box[k] for k in ("x1", "y1", "x2", "y2")],
            (160, 160, 160),
            f"slot {box['track_id'] + 1}",
        )
    rectangle(prediction, row["box"], (0, 0, 255), f"Recorded name {row['named_cow']}")
    for index, box in enumerate(frame["raw_detector_boxes"]):
        rectangle(
            raw,
            [box[k] for k in ("x1", "y1", "x2", "y2")],
            (255, 180, 0),
            f"Proposal {index}",
        )
    for key, panel in (
        ("raw", image),
        ("truth", truth),
        ("mask", prediction),
        ("detector", raw),
    ):
        if not cv2.imwrite(
            str(OUTPUT / f"{row['second']}-{row['track_id']}-{key}.png"), panel
        ):
            raise OSError("Could not save diagnostic image")


def render():
    selected = json.loads(SELECTION.read_text())
    if selected["implementation_sha256"] != digest(Path(__file__)):
        raise ValueError("Diagnostic implementation changed after selection")
    for filename, expected in selected["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError("A diagnostic source changed")
    frames = {
        row["second"]: row
        for row in json.loads(FILES["streaming"].read_text())["timeline"]
    }
    OUTPUT.mkdir(exist_ok=False)
    capture = cv2.VideoCapture(str(FILES["video"]))
    try:
        for panel in selected["panels"].values():
            for case in panel["first_errors"].values():
                if case is not None:
                    render_case(capture, case, frames[case["second"]])
        _, first = read_frame(capture, 0, 20)
        with np.load(FILES["seed_masks"], allow_pickle=False) as archive:
            masks = archive["masks"]
        for index, mask in enumerate(masks):
            image = first.copy()
            image[mask.astype(bool)] = (
                image[mask.astype(bool)] * 0.65 + np.array([0, 140, 255]) * 0.35
            ).astype(np.uint8)
            if not cv2.imwrite(str(OUTPUT / f"seed-{index + 1}.png"), image):
                raise OSError("Could not save original seed")
    finally:
        capture.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("select", "render"))
    args = parser.parse_args()
    select() if args.mode == "select" else render()
