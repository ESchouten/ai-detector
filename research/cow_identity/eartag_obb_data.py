"""Native OBB text-line data, preserving original polygons and excluded groups."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from eartag_ocr import DATA_MANIFEST
from eartag_trocr_data import training_rows

ROOT = Path(__file__).parent
BASE = ROOT / "eartag_dataset_protocol.json"
MODEL = Path(".cache/cow-ear-tags/yolo11n-obb.pt")
OUTPUT = Path(".cache/cow-ear-tags/obb-lines")
AUGMENTATION = {
    name: 0.0
    for name in (
        "hsv_h",
        "hsv_s",
        "hsv_v",
        "degrees",
        "translate",
        "scale",
        "shear",
        "perspective",
        "flipud",
        "fliplr",
        "bgr",
        "mosaic",
        "mixup",
        "cutmix",
        "copy_paste",
        "erasing",
        "multi_scale",
    )
}
AUGMENTATION.update(augmentations=[], auto_augment=None, close_mosaic=0)


def normalized_label(points, width, height):
    value = np.asarray(points, dtype=np.float64).reshape(4, 2)
    if (
        not np.isfinite(value).all()
        or (value < 0).any()
        or (value > [width, height]).any()
        or not cv2.isContourConvex(value.astype(np.float32))
        or cv2.contourArea(value.astype(np.float32)) <= 0
    ):
        raise ValueError(
            "Preserve and report invalid training polygons, never silently clip"
        )
    normalized = value / [width, height]
    return "0 " + " ".join(f"{x:.10f}" for x in normalized.ravel())


def freeze(args):
    import ultralytics

    base = json.loads(BASE.read_text())
    if digest(DATA_MANIFEST) != base["files"][str(DATA_MANIFEST)]:
        raise ValueError("Frozen dataset manifest changed")
    manifest = json.loads(DATA_MANIFEST.read_text())
    selected = training_rows(manifest, base["pilot"])
    if (len(selected), sum(len(r["lines"]) for r in selected)) != (1347, 3243):
        raise ValueError("Require the original complete training subset")
    download = ROOT / "results/2026-10-03/ear-tags/obb-model-download.json"
    if digest(MODEL) != json.loads(download.read_text())["sha256"]:
        raise ValueError("Official OBB checkpoint changed")
    package = Path(ultralytics.__file__).parent
    paths = [
        Path(__file__),
        ROOT / "test_eartag_obb_data.py",
        ROOT / "eartag_trocr_data.py",
        ROOT / "eartag_ocr.py",
        ROOT / "benchmark.py",
        ROOT / "scoring.py",
        BASE,
        DATA_MANIFEST,
        MODEL,
        download,
        package / "cfg/default.yaml",
        *sorted(package.rglob("*.py")),
        *(Path(row["image"]) for row in selected),
    ]
    rows = [
        {
            **{
                key: row[key]
                for key in (
                    "id",
                    "image",
                    "image_sha256",
                    "pixels_sha256",
                    "width",
                    "height",
                    "group",
                )
            },
            "polygons": [line["polygon"] for line in row["lines"]],
        }
        for row in selected
    ]
    write_json(
        args.protocol,
        {
            "scope": "One-class text-line localization inside public tag crops. Same 1347 training images/478 groups/3243 original polygons; all 64 pilot groups excluded. No calibration/reserved images or text labels used. Not full-frame tag detection or animal ownership.",
            "files": {str(path): digest(path) for path in paths},
            "libraries": {
                name: importlib.metadata.version(name)
                for name in (
                    "ultralytics",
                    "torch",
                    "torchvision",
                    "numpy",
                    "opencv-python",
                    "pillow",
                )
            },
            "training": rows,
            "output": str(OUTPUT),
            "image_size": 320,
            "augmentation": AUGMENTATION,
            "validation": "Native training validation path is exactly the same training directory, never the pilot or heldout splits. Its metrics are not accuracy evidence and cannot select the study checkpoint.",
            "geometry": "Original four corners normalized by source width/height with ten decimal places. Preserve original native polygons for eventual strict IoU evaluation. Native OBB converts quadrilateral to minimum-area rectangle; inventory representation ratio and native resized side>=2px criterion before training.",
            "transcripts": "No transcript strings in YOLO labels or this training specification.",
        },
    )


def checked(path):
    value = json.loads(path.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen OBB data input changed: {name}")
    if {name: importlib.metadata.version(name) for name in value["libraries"]} != value[
        "libraries"
    ]:
        raise ValueError("Native OBB data environment changed")
    return value


def copy_training(row, output):
    source = Path(row["image"])
    gray = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if gray is None or list(gray.shape) != [row["height"], row["width"]]:
        raise ValueError("Training image dimensions changed")
    if (
        hashlib.sha256(str(gray.shape).encode() + gray.tobytes()).hexdigest()
        != row["pixels_sha256"]
    ):
        raise ValueError("Inventory grayscale pixels changed")
    image = output / "images/train" / f"{row['id']}.jpg"
    label = output / "labels/train" / f"{row['id']}.txt"
    shutil.copyfile(source, image)
    lines = [normalized_label(p, row["width"], row["height"]) for p in row["polygons"]]
    label.write_text("\n".join(lines) + "\n")
    ratios, errors = [], []
    for original, encoded in zip(row["polygons"], lines, strict=True):
        points = np.asarray(original, np.float32).reshape(4, 2)
        restored = np.asarray(encoded.split()[1:], np.float64).reshape(4, 2) * [
            row["width"],
            row["height"],
        ]
        errors.append(float(np.abs(restored - points).max()))
        size = cv2.minAreaRect(points)[1]
        ratios.append(float(cv2.contourArea(points) / (size[0] * size[1])))
    return {
        "id": row["id"],
        "group": row["group"],
        "lines": len(lines),
        "image": str(image),
        "image_sha256": digest(image),
        "label": str(label),
        "label_sha256": digest(label),
        "source_sha256": row["image_sha256"],
        "maximum_coordinate_roundtrip_error": max(errors),
        "rectangle_area_ratios": ratios,
    }


def native_inventory(output, frozen):
    import torch
    from ultralytics.cfg import get_cfg
    from ultralytics.data.dataset import YOLODataset

    torch.set_num_threads(2)
    dataset = YOLODataset(
        img_path=str(output / "images/train"),
        imgsz=320,
        augment=True,
        hyp=get_cfg(overrides=frozen["augmentation"]),
        task="obb",
        cache=False,
        data={"names": {0: "text_line"}, "nc": 1, "channels": 3},
    )
    labels = sum(len(row["cls"]) for row in dataset.labels)
    sizes, tiny, count = [], [], 0
    for index in range(len(dataset)):
        row = dataset[index]
        boxes = row["bboxes"].numpy()
        height, width = row["img"].shape[-2:]
        sides = boxes[:, 2:4] * [width, height]
        sizes.extend(sides.min(axis=1).tolist())
        count += len(boxes)
        tiny.extend(
            {"image": row["im_file"], "index": int(i), "sides": sides[i].tolist()}
            for i in np.flatnonzero((sides < 2).any(axis=1))
        )
    if len(dataset) != 1347 or labels != 3243 or count != 3243:
        raise ValueError("Native data loader dropped original training images/labels")
    return {
        "images": len(dataset),
        "parsed_labels": labels,
        "transformed_labels": count,
        "below_two_pixels": tiny,
        "minimum_resized_side": min(sizes),
        "transforms": str(dataset.transforms),
    }


def prepare(args):
    frozen = checked(args.protocol)
    output = Path(frozen["output"])
    output.mkdir()
    for relative in ("images/train", "labels/train"):
        (output / relative).mkdir(parents=True)
    cv2.setNumThreads(2)
    rows = [copy_training(row, output) for row in frozen["training"]]
    yaml = output / "data.yaml"
    yaml.write_text(
        f"path: {json.dumps(str(output.resolve()))}\ntrain: images/train\nval: images/train\nnames:\n  0: text_line\n"
    )
    inventory = native_inventory(output, frozen)
    ratios = [v for row in rows for v in row["rectangle_area_ratios"]]
    result = {
        "protocol_sha256": digest(args.protocol),
        "complete": True,
        "rows": rows,
        "data_yaml": str(yaml),
        "data_yaml_sha256": digest(yaml),
        "native_inventory": inventory,
        "groups": len({row["group"] for row in rows}),
        "maximum_coordinate_roundtrip_error": max(
            row["maximum_coordinate_roundtrip_error"] for row in rows
        ),
        "minimum_rectangle_area_ratio": min(ratios),
        "median_rectangle_area_ratio": float(np.median(ratios)),
    }
    write_json(output / "manifest.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "prepare"))
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else OUTPUT
    if target.exists():
        parser.error("Preserve previous frozen data and outputs")
    (freeze if args.mode == "freeze" else prepare)(args)
