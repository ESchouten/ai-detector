"""Freeze every extended named error, then render prediction and truth separately."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_birth_extended import WINDOWS, checked_inputs
from detection_errors import overlaps
from detection_reserved_audit import rectangle
from video_assessment import annotations, pair_boxes, pixels_hash, truth_at

from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/detection"
PROTOCOL = ROOT / "detection_birth_extended_protocol.json"
RUN = Path(".cache/cow-cutie/crowded-joint-extended/streaming.json")
BASELINE = Path(".cache/cow-cutie/streaming-reserved/streaming.json")
SELECTED = RESULTS / "extended-error-selection.json"
IMAGES = Path(".cache/cow-cutie/extended-error-audit")
ANNOTATIONS = Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz")
PICKLE = Path("datasets/8-calves/video/pmfeed_4_3_16.pkl")


def named_outcomes(frame, truth):
    boxes = [BoundingBox(**row) for row in frame["boxes"]]
    paired = pair_boxes(boxes, truth)
    return {
        box.track_id: {
            "kind": "unmatched_named"
            if index not in paired
            else "correct_name"
            if truth[paired[index]]["cow"] == box.track_id + 1
            else "wrong_name",
            "assigned_cow": truth[paired[index]]["cow"] if index in paired else None,
            "box": vars(box),
        }
        for index, box in enumerate(boxes)
        if box.track_id in frame["named_track_ids"]
    }


def collect_cases(current, baseline, records, clip):
    old_rows = {r["second"]: r for r in baseline["timeline"]}
    rows, old_errors = [], []
    for frame in current["timeline"]:
        if not any(a <= frame["second"] <= b for a, b in WINDOWS):
            continue
        second = frame["second"]
        truth = truth_at(
            records, frame["publisher_frame"], clip["width"], clip["height"]
        )
        old = old_rows[second]
        if old["source_pixels_sha256"] != frame["source_pixels_sha256"]:
            raise ValueError("Old eight-seed comparison uses different pixels")
        old_named = named_outcomes(old, truth)
        old_errors.extend(
            {"second": second, "cow": track + 1, "kind": item["kind"]}
            for track, item in old_named.items()
            if item["kind"] != "correct_name"
        )
        for track, item in named_outcomes(frame, truth).items():
            if item["kind"] == "correct_name":
                continue
            if item["kind"] != "unmatched_named":
                raise ValueError("Published zero wrong-known errors no longer matches")
            partner = next(
                r for r in frame["reciprocal_pairs"] if r["track_id"] == track
            )
            rows.append(
                {
                    "index": len(rows),
                    "second": second,
                    "named_cow": track + 1,
                    "track_id": track,
                    "publisher_frame": frame["publisher_frame"],
                    "source_pixels_sha256": frame["source_pixels_sha256"],
                    "mask_path": str(RUN.parent / "masks" / f"{second:g}.png"),
                    "mask_sha256": frame["mask_sha256"],
                    "box": item["box"],
                    "probabilities": next(
                        r for r in frame["objects"] if r["track_id"] == track
                    ),
                    "paired_proposal_index": partner["proposal_index"],
                    "raw_proposals": frame["raw_detector_boxes"],
                    "other_propagated_boxes": frame["boxes"],
                    "old_eight_seed_same_slot": old_named.get(
                        track, {"kind": "not_named"}
                    ),
                }
            )
    return rows, old_errors


def select():
    if SELECTED.exists():
        raise FileExistsError("Preserve the original complete error selection")
    protocol, clip, _, _ = checked_inputs(PROTOCOL)
    current = json.loads(RUN.read_text())
    baseline = json.loads(BASELINE.read_text())
    report_path = RESULTS / "crowded-joint-extended.json"
    official = json.loads(report_path.read_text())
    if not current["complete"] or official["sources"][str(RUN)] != digest(RUN):
        raise ValueError("Require the complete immutable strict result")
    records, _ = annotations(
        SimpleNamespace(annotations=ANNOTATIONS, source_pickle=PICKLE)
    )
    rows, old_errors = collect_cases(current, baseline, records, clip)
    counts = {
        str(start): sum(start <= r["second"] <= stop for r in rows)
        for start, stop in WINDOWS
    }
    if counts != {"1800": 5, "2700": 29} or any(
        counts[k] != official["conditions"][k]["naming_counts"]["unmatched_named"]
        for k in counts
    ):
        raise ValueError("Audit must retain every one of all34 strict named errors")
    files = dict(protocol["files"])
    for path in (
        Path(__file__),
        PROTOCOL,
        RUN,
        BASELINE,
        report_path,
        ROOT / "detection_reserved_audit.py",
        ROOT / "detection_errors.py",
    ):
        files[str(path)] = digest(path)
    for row in rows:
        if digest(Path(row["mask_path"])) != row["mask_sha256"]:
            raise ValueError("Selected mask changed before freezing")
        files[row["mask_path"]] = row["mask_sha256"]
    write_json(
        SELECTED,
        {
            "scope": "Post-result all-error diagnostic; all5+29namedunmatched outputs selected before opening error pixels. No threshold change, exclusion, rescore or claim that unmatched boxes are biologically wrong/right.",
            "selection": "Complete strict one-to-one IoU>=.5 error set, chronological timestamp then original output order. No sampling/cherry-picking. Truth determines only error membership; prediction-only image panels omit all publisher boxes/identity hints until separate truth overlay review.",
            "source_clip": protocol["inputs"]["clip"],
            "counts": counts,
            "rows": rows,
            "old_eight_seed_all_named_errors": old_errors,
            "exact_same_second_cow_error_recurrences": [
                r["index"]
                for r in rows
                if r["old_eight_seed_same_slot"]["kind"] != "correct_name"
                and r["old_eight_seed_same_slot"]["kind"] != "not_named"
            ],
            "files": files,
        },
    )
    print(
        json.dumps(
            {
                "path": str(SELECTED),
                "sha256": digest(SELECTED),
                "counts": counts,
                "rows": len(rows),
            }
        )
    )


def bounds(box):
    return [box[k] for k in ("x1", "y1", "x2", "y2")]


def header(image, lines):
    result = cv2.copyMakeBorder(
        image, 65, 0, 0, 0, cv2.BORDER_CONSTANT, value=(245, 245, 245)
    )
    for y, text in zip((22, 47), lines, strict=True):
        cv2.putText(
            result,
            text,
            (8, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )
    return result


def save(path, image):
    if not cv2.imwrite(str(path), image):
        raise OSError("Failed to preserve audit image")
    return {"path": str(path), "sha256": digest(path)}


def draw_case(source, mask, row, truth):
    prediction, foreground = source.copy(), source.copy()
    selected = mask == row["named_cow"]
    foreground[selected] = (
        0.6 * foreground[selected] + 0.4 * np.array([0, 128, 255])
    ).astype(np.uint8)
    proposal = row["raw_proposals"][row["paired_proposal_index"]]
    for canvas in (prediction, foreground):
        rectangle(canvas, bounds(proposal), (255, 255, 0), "Raw paired proposal")
        rectangle(canvas, bounds(row["box"]), (0, 0, 255), f"Named {row['named_cow']}")
    title = f"#{row['index']:02d} | t={row['second']:g}s | original name={row['named_cow']} | p10={row['probabilities']['p10_probability']:.3f}"
    blind = header(
        np.concatenate((prediction, foreground), axis=1),
        [
            title,
            "Left: actual named box + raw paired proposal. Right: same plus original stable mask. No truth overlay.",
        ],
    )
    with_truth = foreground.copy()
    for animal in truth:
        rectangle(
            with_truth,
            animal["box"],
            (0, 255, 0) if animal["cow"] == row["named_cow"] else (150, 150, 150),
            f"GT {animal['cow']}",
        )
    paired_overlap = overlaps(BoundingBox(**proposal), truth)
    original_overlap = overlaps(BoundingBox(**row["box"]), truth)
    own = next((x for x in original_overlap if x["cow"] == row["named_cow"]), None)
    info = (
        "Own published IoU="
        + (f"{own['iou']:.3f}" if own else "absent")
        + "; boxes are immutable, this is diagnosis only"
    )
    annotated = header(with_truth, [title, info])
    return (
        blind,
        annotated,
        {
            "truth": truth,
            "mask_lcc_overlaps": original_overlap,
            "paired_raw_proposal_overlaps": paired_overlap,
        },
    )


def sheets(images, kind, width):
    pages = []
    for offset in range(0, len(images), 6):
        thumb_height = 333 if kind == "prediction" else 665
        page = np.full((3 * thumb_height, 2 * width, 3), 245, np.uint8)
        for index, item in enumerate(images[offset : offset + 6]):
            image = cv2.imread(item["path"])
            image = cv2.resize(
                image, (width, thumb_height), interpolation=cv2.INTER_AREA
            )
            y, x = divmod(index, 2)
            page[
                y * thumb_height : (y + 1) * thumb_height, x * width : (x + 1) * width
            ] = image
        pages.append(save(IMAGES / f"{kind}-sheet-{offset // 6 + 1:02d}.jpg", page))
    return pages


def render():
    selection = json.loads(SELECTED.read_text())
    for path, expected in selection["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen diagnostic input changed: {path}")
    IMAGES.mkdir(parents=True, exist_ok=False)
    records, _ = annotations(
        SimpleNamespace(annotations=ANNOTATIONS, source_pickle=PICKLE)
    )
    capture = cv2.VideoCapture(str(Path(selection["source_clip"]) / "sampled.avi"))
    pictures, truth_pictures, diagnostics = [], [], []
    try:
        for row in selection["rows"]:
            capture.set(cv2.CAP_PROP_POS_FRAMES, round(row["second"] * 2))
            ok, source = capture.read()
            if not ok or pixels_hash(source) != row["source_pixels_sha256"]:
                raise ValueError("Review source pixels differ from frozen inference")
            mask = cv2.imread(row["mask_path"], cv2.IMREAD_UNCHANGED)
            truth = truth_at(
                records, row["publisher_frame"], source.shape[1], source.shape[0]
            )
            blind, annotated, values = draw_case(source, mask, row, truth)
            pictures.append(save(IMAGES / f"{row['index']:02d}-prediction.png", blind))
            truth_pictures.append(
                save(IMAGES / f"{row['index']:02d}-truth.png", annotated)
            )
            diagnostics.append(
                {
                    "index": row["index"],
                    "second": row["second"],
                    "named_cow": row["named_cow"],
                    **values,
                }
            )
    finally:
        capture.release()
    # Two columns per page; prediction views are1600wide before reduction.
    report = {
        "selection_sha256": digest(SELECTED),
        "prediction_only": pictures,
        "truth_overlay": truth_pictures,
        "truth_diagnostics": diagnostics,
        "prediction_sheets": sheets(pictures, "prediction", 800),
        "truth_sheets": sheets(truth_pictures, "truth", 800),
        "scope": "All34cases preserved, no image-based reselection. Inspect prediction-only panels first, then separate publisher overlays. No altered metric or automatic biological classification.",
    }
    write_json(RESULTS / "extended-error-render.json", report)
    print(
        json.dumps(
            {
                "cases": len(diagnostics),
                "directory": str(IMAGES),
                "selection_sha256": digest(SELECTED),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("select", "render"))
    args = parser.parse_args()
    cv2.setNumThreads(2)
    (select if args.mode == "select" else render)()
