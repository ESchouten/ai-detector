"""CPU-only evidence ledger for the completed, unchanged entry baseline."""

import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_corroboration import maximum_iou
from passage_entry_control import source_image
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
EXECUTION = ROOT / "passage_entry_execution.json"
DIRECTORY = Path(".cache/cow-passage-entry-control")
REPORT = ROOT / "results/2026-10-03/purdue-entry-baseline.json"
OUTPUT = ROOT / "results/2026-10-03/purdue-entry-forensics.json"


def frame_evidence(frame, truth, mask):
    box = frame["boxes"][0] if frame["boxes"] else None
    objects = frame["objects"]
    pair = frame["reciprocal_pairs"][0] if frame["reciprocal_pairs"] else None
    proposal = frame["raw_detector_boxes"][pair["proposal_index"]] if pair else None
    overlaps = {}
    for animal in truth["boxes"]:
        scaled = {
            key: coord / 1.5
            for key, coord in zip(("x1", "y1", "x2", "y2"), animal["box"], strict=True)
        }
        overlaps[str(animal["cow"])] = maximum_iou(box, [scaled]) if box else 0.0
    return {
        "second": frame["second"],
        "slot": 1,
        "original_slot_area": int(np.count_nonzero(mask)),
        "p10": objects[0]["p10_probability"] if objects else None,
        "mean_probability": objects[0]["mean_probability"] if objects else None,
        "raw_proposal_count": len(frame["raw_detector_boxes"]),
        "reciprocal_proposal_index": pair["proposal_index"] if pair else None,
        "reciprocal_iou": maximum_iou(box, [proposal]) if proposal else None,
        "reciprocal_proposal": proposal,
        "lcc_box_iou_with_visible_truth": overlaps,
        "name_displayed": bool(frame["named_track_ids"]),
        "conflicted_ids": frame["conflicted_ids"],
    }


def render_frame(image, mask, frame, evidence, target):
    original, propagated = image.copy(), image.copy()
    for index, box in enumerate(frame["raw_detector_boxes"]):
        start, end = (box["x1"], box["y1"]), (box["x2"], box["y2"])
        cv2.rectangle(original, start, end, (0, 230, 255), 3)
        cv2.putText(
            original,
            f"proposal {index}: {box['confidence']:.3f}",
            start,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 230, 255),
            2,
        )
    pixels = mask == 1
    propagated[pixels] = (propagated[pixels] * 0.6 + np.array([0, 100, 0])).astype(
        np.uint8
    )
    for box in frame["boxes"]:
        cv2.rectangle(
            propagated,
            (box["x1"], box["y1"]),
            (box["x2"], box["y2"]),
            (255, 255, 255),
            3,
        )
    tile = Image.new("RGB", (1280, 420), "white")
    for x, picture in ((0, original), (640, propagated)):
        tile.paste(Image.fromarray(picture[:, :, ::-1]).resize((640, 360)), (x, 60))
    text = ImageDraw.Draw(tile)
    p10, overlap = evidence["p10"], evidence["reciprocal_iou"]
    name = "5676" if evidence["name_displayed"] else "hidden"
    text.text(
        (8, 8),
        f"{frame['second']:.1f}s | name={name} | slot area={evidence['original_slot_area']} | p10={p10} | reciprocal IoU={overlap}",
        fill="black",
    )
    text.text(
        (8, 33),
        "Left: original pixels + fresh raw detector proposals. Right: original slot mask + LCC bounds.",
        fill="black",
    )
    tile.save(target)


def execute():
    protocol = json.loads(EXECUTION.read_text())
    value = json.loads((DIRECTORY / "predictions.json").read_text())
    score = json.loads(REPORT.read_text())
    if not value["complete"] or value["protocol_sha256"] != digest(EXECUTION):
        raise ValueError("Forensics requires the complete frozen baseline")
    if score["sources"][str(DIRECTORY / "predictions.json")] != digest(
        DIRECTORY / "predictions.json"
    ):
        raise ValueError("Baseline predictions changed after strict scoring")
    for path in (
        protocol["inputs"]["frames"],
        protocol["inputs"]["annotations"],
        str(ROOT / "detection_corroboration.py"),
    ):
        if path in protocol["files"] and digest(Path(path)) != protocol["files"][path]:
            raise ValueError("Source or matching helper changed")
    source = json.loads(Path(protocol["inputs"]["frames"]).read_text())
    truth = json.loads(Path(protocol["inputs"]["annotations"]).read_text())
    directory = DIRECTORY / "forensics"
    directory.mkdir(exist_ok=False)
    rows = []
    for index, (frame, original, annotation) in enumerate(
        zip(value["timeline"], source["rows"], truth["frames"], strict=True)
    ):
        path = DIRECTORY / "masks" / f"{index:03d}.png"
        if digest(path) != frame["mask_sha256"]:
            raise ValueError("Frozen mask changed")
        mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        row = frame_evidence(frame, annotation, mask)
        target = directory / f"{index:03d}.jpg"
        render_frame(source_image(original), mask, frame, row, target)
        rows.append(
            {**row, "review_image": str(target), "review_image_sha256": digest(target)}
        )
    sheets = []
    for page, start in enumerate(range(0, len(rows), 12)):
        selected = rows[start : start + 12]
        sheet = Image.new("RGB", (1280, 210 * ((len(selected) + 1) // 2)), "white")
        for index, row in enumerate(selected):
            picture = Image.open(row["review_image"]).resize((640, 210))
            sheet.paste(picture, (index % 2 * 640, index // 2 * 210))
        target = directory / f"sheet-{page + 1}.jpg"
        sheet.save(target)
        sheets.append({"path": str(target), "sha256": digest(target)})
    write_json(
        OUTPUT,
        {
            "scope": "Posthoc causal diagnostics, no parameter or outcome changes; truth IoU is used only here, never by inference.",
            "strict_scoring_completed_before_continuity_integration": True,
            "inputs": {
                str(p): digest(p)
                for p in (
                    EXECUTION,
                    DIRECTORY / "predictions.json",
                    REPORT,
                    Path(__file__),
                )
            },
            "rows": rows,
            "sheets": sheets,
        },
    )
    print(json.dumps(rows))


if __name__ == "__main__":
    cv2.setNumThreads(2)
    execute()
