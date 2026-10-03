"""Fit whole-animal and coat-torso detection using only frozen June8 passages."""

import argparse
import json
import shutil
from pathlib import Path

from benchmark import digest, write_json

PROTOCOL = Path(__file__).with_name("passage_training_protocol.json")


def checked_box(value, width, height):
    if len(value) != 4:
        raise ValueError("Annotation box must contain four coordinates")
    x1, y1, x2, y2 = value
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("Annotation box must lie within its native source image")
    return (
        (x1 + x2) / (2 * width),
        (y1 + y2) / (2 * height),
        (x2 - x1) / width,
        (y2 - y1) / height,
    )


def yolo_labels(frame, width, height):
    lines = []
    for box in frame["boxes"]:
        for category, value in enumerate((box["box"], box.get("torso_box"))):
            if value is not None:
                normalized = checked_box(value, width, height)
                lines.append(f"{category} " + " ".join(f"{v:.8f}" for v in normalized))
    return "\n".join(lines) + ("\n" if lines else "")


def load_annotations(paths, source):
    result = {}
    for path in paths:
        annotations = json.loads(path.read_text())
        if annotations["source_manifest_sha256"] != digest(source):
            raise ValueError("Annotations do not describe the frozen first-day source")
        for frame in annotations["frames"]:
            key = frame["clip"], frame["frame"]
            if key in result:
                raise ValueError("Two annotators supplied the same frame")
            result[key] = frame
    return result


def write_sample(source, annotation, split, output):
    path = Path(source["path"])
    if digest(path) != source["sha256"]:
        raise ValueError("Native source pixels changed after independent annotation")
    for key in ("clip", "frame", "pixels_sha256", "principal_cow"):
        if source[key] != annotation[key]:
            raise ValueError(f"Annotation source binding differs: {key}")
    stem = f"{source['clip']}-{source['frame']:06}"
    image = output / "images" / split / f"{stem}.png"
    label = output / "labels" / split / f"{stem}.txt"
    image.parent.mkdir(parents=True, exist_ok=True)
    label.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, image)
    label.write_text(yolo_labels(annotation, source["width"], source["height"]))
    return {
        "clip": source["clip"],
        "frame": source["frame"],
        "split": split,
        "image": str(image),
        "image_sha256": digest(image),
        "label": str(label),
        "label_sha256": digest(label),
        "animals": len(annotation["boxes"]),
        "torsos": sum(b.get("torso_box") is not None for b in annotation["boxes"]),
    }


def prepare(args):
    protocol = json.loads(args.protocol.read_text())
    source_path = Path(protocol["source_manifest"])
    if digest(source_path) != protocol["source_manifest_sha256"]:
        raise ValueError("First-day source manifest changed")
    source = json.loads(source_path.read_text())
    annotations = load_annotations(args.annotations, source_path)
    if set(annotations) != {(r["clip"], r["frame"]) for r in source["frames"]}:
        raise ValueError("Every frozen first-day frame must be independently annotated")
    if args.output.exists():
        raise ValueError("Preserve the previously prepared adaptation dataset")
    rows, excluded = [], []
    for row in source["frames"]:
        annotation = annotations[row["clip"], row["frame"]]
        if any(b["cow"] in protocol["unknown_cows"] for b in annotation["boxes"]):
            excluded.append({"clip": row["clip"], "frame": row["frame"]})
            continue
        split = next(
            s for s, clips in protocol["splits"].items() if row["clip"] in clips
        )
        rows.append(write_sample(row, annotation, split, args.output))
    yaml = args.output / "data.yaml"
    yaml.write_text(
        f"path: {args.output.resolve()}\ntrain: images/train\nval: images/validation\n"
        "names: [whole_visible_cow, coat_torso]\n"
    )
    write_json(
        args.output / "prepared.json",
        {
            "protocol_sha256": digest(args.protocol),
            "annotations": {str(p): digest(p) for p in args.annotations},
            "source_manifest_sha256": digest(source_path),
            "preparation_source_sha256": digest(Path(__file__)),
            "yaml_sha256": digest(yaml),
            "excluded_withheld_identity_frames": excluded,
            "frames": rows,
        },
    )


def train(args):
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(2)
    protocol = json.loads(args.protocol.read_text())
    prepared = json.loads((args.output / "prepared.json").read_text())
    if prepared["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Prepared localization data uses a different frozen protocol")
    checks = {
        **prepared["annotations"],
        str(args.output / "data.yaml"): prepared["yaml_sha256"],
    }
    for row in prepared["frames"]:
        checks[row["image"]] = row["image_sha256"]
        checks[row["label"]] = row["label_sha256"]
    checks[protocol["initial_model"]["path"]] = protocol["initial_model"]["sha256"]
    if any(digest(Path(path)) != expected for path, expected in checks.items()):
        raise ValueError("A frozen training input changed")
    run = args.output / "training"
    if run.exists():
        raise ValueError("Preserve the previous adaptation run")
    YOLO(protocol["initial_model"]["path"]).train(
        data=str(args.output / "data.yaml"),
        project=str(args.output.resolve()),
        name="training",
        plots=False,
        cache="ram",
        **protocol["training"],
    )
    write_json(
        run / "provenance.json",
        {
            "protocol_sha256": digest(args.protocol),
            "prepared_sha256": digest(args.output / "prepared.json"),
            "training_source_sha256": digest(Path(__file__)),
            "best_model_sha256": digest(run / "weights/best.pt"),
            "note": "June8-only two-class localization; no biological identity training",
        },
    )


def runtime_protocol(args):
    training = json.loads(args.protocol.read_text())
    provenance_path = args.output / "training/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    if provenance["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Training did not use the requested frozen settings")
    model = args.output / "training/weights/best.pt"
    if digest(model) != provenance["best_model_sha256"]:
        raise ValueError("Selected training checkpoint changed")
    here = Path(__file__).parent
    result = json.loads((here / "passage_cadence_protocol.json").read_text())
    result["detector"] = {
        **training["detection"],
        "model": str(model),
        "sha256": digest(model),
        "classes": ["whole_visible_cow", "coat_torso"],
        "class_ids": [0, 1],
        "precision": "FP32 on MPS",
        "tracking_classes": [0],
    }
    result["adaptation"] = {
        "training_protocol": str(args.protocol),
        "training_protocol_sha256": digest(args.protocol),
        "training_provenance_sha256": digest(provenance_path),
        "prepared_data_sha256": digest(args.output / "prepared.json"),
        "source": "June8-only two-class whole-visible-animal and visible-coat-torso boxes",
        "crop_policy": training["crop_policy"],
    }
    for filename in ("passage_torso.py", "passage_torso_detection.py"):
        path = here / filename
        result["source_hashes"][str(path)] = digest(path)
    result["selection"] = (
        "Fixed first-day-only adaptation. June9 is exposed regression; no claim of new blind testing or post-query tuning."
    )
    result["query_pixels_opened_at_freeze"] = True
    result["query_truth_requirement"] = (
        "Existing independent105-frame annotations are unchanged and must be bound in the final query freeze."
    )
    write_json(args.output / "runtime-protocol.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "train", "runtime-protocol"))
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--annotations", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare" and not args.annotations:
        parser.error("prepare requires independently reviewed --annotations")
    {"prepare": prepare, "train": train, "runtime-protocol": runtime_protocol}[
        args.action
    ](args)
