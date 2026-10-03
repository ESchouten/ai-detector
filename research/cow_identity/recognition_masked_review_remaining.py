"""Render only the remaining frozen reference questions, without model calls."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
from benchmark import digest, write_json
from PIL import Image, ImageDraw, ImageFont
from recognition_masked_pilot import CLIP, ROOT, RUN, checked, render_frame

RESULTS = ROOT / "results/2026-10-03/recognition"
PRIOR_PROTOCOL = ROOT / "recognition_masked_pilot_v2_protocol.json"
PRIOR_SELECTION = RESULTS / "masked-reference-pilot-v2-selection.json"
PRIOR_RENDER = Path(".cache/cow-masked-reference-pilot-v2/manifest.json")


def remaining(selection):
    used = {(r["track_id"], r["second"]) for r in selection["pilot"]}
    rows = [
        r
        for r in selection["winners"]
        if r["second"] != 0 and (r["track_id"], r["second"]) not in used
    ]
    rows.sort(
        key=lambda r: hashlib.sha256(
            f"remaining-review-v1:{r['track_id']}:{r['second']}".encode()
        ).hexdigest()
    )
    return [{**row, "candidate": 12 + i} for i, row in enumerate(rows)]


def unanimous():
    reviews = []
    for name in ("root", "cattle", "audit"):
        record = json.loads(
            (RESULTS / f"masked-reference-pilot-review-{name}.json").read_text()
        )
        rows = record.get("rows", record.get("decisions"))
        reviews.append(
            {
                row["candidate"]: row["cow"]
                for row in rows
                if row.get("accepted", row.get("decision") == "accept")
            }
        )
    return {
        k: v
        for k, v in reviews[0].items()
        if all(other.get(k) == v for other in reviews[1:])
    }


def freeze(path):
    prior = checked(PRIOR_PROTOCOL)
    references = json.loads(PRIOR_RENDER.read_text())["rows"]
    for row in references:
        if digest(Path(row["foreground"]["path"])) != row["foreground"]["sha256"]:
            raise ValueError("A previously rendered reference photo changed")
    sources = [
        Path(__file__),
        ROOT / "test_recognition_masked_remaining.py",
        PRIOR_PROTOCOL,
        PRIOR_SELECTION,
        PRIOR_RENDER,
        *[Path(row["foreground"]["path"]) for row in references],
        *[
            RESULTS / f"masked-reference-pilot-review-{name}.json"
            for name in ("root", "cattle", "audit")
        ],
    ]
    selected = remaining(json.loads(PRIOR_SELECTION.read_text()))
    accepted = unanimous()
    if len(selected) != 40 or set(accepted) != {0, 1, 2, 3, 5, 10, 11}:
        raise ValueError(
            "The authorized remaining questions and reference consensus changed"
        )
    write_json(
        path,
        {
            "status": "FROZEN_RENDER_AND_REVIEW_ONLY",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "files": {**prior["files"], **{str(p): digest(p) for p in sources}},
            "questions": selected,
            "confirmed_pilot_references": accepted,
            "scope": "Exactly forty remaining preselected winners; no threshold adjustment, replacement, model inference, encoding or new source selection.",
            "order": "SHA256 of remaining-review-v1:zero_based_track:second; candidate IDs12..51. Expected slot and quality are absent from review sheets.",
            "review": "Match against all six initial and separately seven unanimously reviewed pilot references. Preserve uncertainty. Original pilot uncertainties are not replaced. This is AI review with known prior ordering exposure, not blinded farmer truth.",
            "question_budget": {
                "already_confirmed_initial": 6,
                "prior_pilot_questions": 12,
                "remaining_questions": 40,
                "total_unique_selected": 58,
            },
        },
    )


def pasted(canvas, image, position, size):
    scale = min(size[0] / image.width, size[1] / image.height)
    image = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.NEAREST,
    )
    canvas.paste(
        image,
        (
            position[0] + (size[0] - image.width) // 2,
            position[1] + (size[1] - image.height) // 2,
        ),
    )


def sheet_references(rows, output, name):
    canvas = Image.new("RGB", (1800, 500 * ((len(rows) + 2) // 3)), "white")
    draw, font = ImageDraw.Draw(canvas), ImageFont.load_default(size=27)
    for n, (label, path) in enumerate(rows):
        x, y = n % 3 * 600, n // 3 * 500
        draw.text((x + 15, y + 15), label, fill="black", font=font)
        pasted(canvas, Image.open(path), (x + 20, y + 65), (560, 420))
    path = output / name
    canvas.save(path)
    return str(path), digest(path)


def sheets(rows, output, protocol):
    paths = {}
    for row in rows:
        canvas = Image.new("RGB", (1240, 680), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (20, 15),
            f"Candidate {row['candidate']:02d} - second {row['second']}",
            fill="black",
            font=ImageFont.load_default(size=27),
        )
        canvas.paste(Image.open(row["context"]["path"]), (20, 80))
        pasted(canvas, Image.open(row["foreground"]["path"]), (840, 80), (380, 580))
        path = output / f"candidate-{row['candidate']:02d}-review.png"
        canvas.save(path)
        paths[str(path)] = digest(path)
    prior = json.loads(PRIOR_RENDER.read_text())["rows"]
    initial = sorted(
        (r for r in prior if "candidate" not in r), key=lambda r: r["track_id"]
    )
    paths.update(
        [
            sheet_references(
                [
                    (
                        f"Initial confirmed cow {r['track_id'] + 1}",
                        r["foreground"]["path"],
                    )
                    for r in initial
                ],
                output,
                "initial-references.png",
            )
        ]
    )
    accepted = protocol["confirmed_pilot_references"]
    refs = sorted(
        (r for r in prior if str(r.get("candidate")) in accepted),
        key=lambda r: r["candidate"],
    )
    paths.update(
        [
            sheet_references(
                [
                    (
                        f"Reviewed cow {accepted[str(r['candidate'])]} - P{r['candidate']:02d}",
                        r["foreground"]["path"],
                    )
                    for r in refs
                ],
                output,
                "confirmed-pilot-references.png",
            )
        ]
    )
    return paths


def render(protocol_path, output):
    protocol = checked(protocol_path)
    selected = protocol["questions"]
    run = json.loads((RUN / "streaming.json").read_text())
    clip = json.loads((CLIP / "sampled.json").read_text())
    seconds = {row["second"] for row in selected}
    if max(seconds) > 629:
        raise ValueError("Review cannot decode beyond frozen enrollment scope")
    output.mkdir(parents=True, exist_ok=False)
    capture, rows = cv2.VideoCapture(str(CLIP / "sampled.avi")), []
    try:
        for source in clip["rows"]:
            second = source["second"]
            if second > max(seconds):
                break
            if not capture.grab():
                raise ValueError("Source clip ended prematurely")
            if second in seconds:
                ok, image = capture.retrieve()
                if not ok:
                    raise ValueError("Source frame could not decode")
                rows.extend(render_frame(image, int(second), selected, run, output))
    finally:
        capture.release()
    if len(rows) != len(selected):
        raise ValueError("Every frozen question must be rendered")
    write_json(
        output / "manifest.json",
        {
            "status": "READY_FOR_INDEPENDENT_REVIEW_NOT_ENROLLED",
            "protocol_sha256": digest(protocol_path),
            "rows": rows,
            "sheets": sheets(rows, output, protocol),
            "labels": "Expected slots in metadata are not accepted biological labels. Sheet IDs alone carry no expected identity.",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "render"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Use a fresh output; frozen artifacts are immutable")
    freeze(args.protocol) if args.mode == "freeze" else render(
        args.protocol, args.output
    )
