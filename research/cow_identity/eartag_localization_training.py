"""One frozen native Ultralytics head/tag pilot; no held-out images or OCR."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache/cow-eartag-localization-training"
RESULTS = ROOT / "research/cow_identity/results/2026-10-03/ear-tags"
ROI = RESULTS / "ownership-two-class-roi-v2.json"
MODEL = ROOT / ".cache/cow-video-policy-cache/yolo11s.pt"
MODEL_SHA = "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5"
ROI_SHA = "731d0ab42dba1a7bea78abbbbf3bb97f681b9d76db38aa85857b30e93a228905"
LIMIT = 8 * 1024**3
os.environ["YOLO_CONFIG_DIR"] = str(CACHE / "settings")
os.environ["YOLO_OFFLINE"] = "true"
os.environ["ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS"] = "1"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sdk():
    import torch
    import ultralytics
    from ultralytics.utils import SETTINGS

    SETTINGS.update(
        dict.fromkeys(
            (
                "sync",
                "clearml",
                "comet",
                "dvc",
                "hub",
                "mlflow",
                "neptune",
                "raytune",
                "tensorboard",
                "wandb",
            ),
            False,
        )
    )
    torch.set_num_threads(2)
    return torch, ultralytics


def xywh(box, width, height):
    x1, y1, x2, y2 = box
    if not all(math.isfinite(v) for v in box) or not (
        0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
    ):
        raise ValueError("Positive finite clipped ROI coordinates required")
    return [
        (x1 + x2) / (2 * width),
        (y1 + y2) / (2 * height),
        (x2 - x1) / width,
        (y2 - y1) / height,
    ]


def data():
    import numpy as np
    from PIL import Image

    if digest(ROI) != ROI_SHA or digest(MODEL) != MODEL_SHA:
        raise ValueError("Reviewed ROI or official weights changed")
    document = json.loads(ROI.read_text())
    target = CACHE / "dataset"
    if target.exists():
        raise ValueError("Preserve previous data package")
    (target / "images").mkdir(parents=True)
    (target / "labels").mkdir()
    rows = []
    for index, row in enumerate(document["rows"]):
        source = ROOT / row["image"]
        if digest(source) != row["image_sha256"]:
            raise ValueError("Source pixels changed")
        image = Image.open(source).convert("RGB").crop(row["native_xyxy"])
        path = target / "images" / f"image{index:02}.png"
        image.save(path)
        labels = []
        for cls, kind in enumerate(("heads", "tags")):
            for obj in row[kind]:
                labels.append(
                    f"{cls} "
                    + " ".join(f"{v:.12f}" for v in xywh(obj["xyxy"], *image.size))
                )
        label = target / "labels" / f"image{index:02}.txt"
        label.write_text("\n".join(labels) + "\n")
        array = np.array(image)
        rows.append(
            {
                "source_id": row["id"],
                "image": str(path),
                "image_sha256": digest(path),
                "label": str(label),
                "label_sha256": digest(label),
                "native_roi": row["native_xyxy"],
                "pixels_sha256": hashlib.sha256(array.tobytes()).hexdigest(),
                "shape": list(array.shape),
                "heads": len(row["heads"]),
                "tags": len(row["tags"]),
            }
        )
    if (
        len(rows) != 13
        or sum(r["heads"] for r in rows) != 25
        or sum(r["tags"] for r in rows) != 42
    ):
        raise ValueError("Expected exact reviewed 13-source/25-head/42-tag set")
    names = "\n".join(r["image"] for r in rows) + "\n"
    for name in ("train.txt", "validation.txt"):
        (target / name).write_text(names)
    # JSON is valid YAML; native loader resolves two explicitly identical lists.
    write(
        target / "data.yaml",
        {
            "path": str(target),
            "train": "train.txt",
            "val": "validation.txt",
            "names": {0: "head", 1: "ear_tag"},
        },
    )
    manifest = {
        "roi_sha256": digest(ROI),
        "rows": rows,
        "review": "Parent inspected all13 ROI overlays before outputs. cow603 corrected left ear independently re-reviewed and approved. AI-reviewed, not human-certified. Training-only validation deliberately reuses the same13crops; never evidence of generalization.",
    }
    write(CACHE / "data-manifest.json", manifest)
    return manifest


def arguments():
    from ultralytics.cfg import get_cfg

    overrides = {
        "model": str(MODEL),
        "data": str(CACHE / "dataset/data.yaml"),
        "task": "detect",
        "mode": "train",
        "device": "mps",
        "epochs": 20,
        "batch": 2,
        "nbs": 2,
        "imgsz": 1280,
        "amp": False,
        "quantize": 32,
        "optimizer": "AdamW",
        "lr0": 0.0001,
        "lrf": 1.0,
        "weight_decay": 0.0005,
        "warmup_epochs": 0.0,
        "warmup_bias_lr": 0.0,
        "patience": 0,
        "seed": 17,
        "deterministic": True,
        "workers": 0,
        "cache": False,
        "project": str(CACHE),
        "name": "run",
        "exist_ok": False,
        "save": True,
        "save_period": -1,
        "val": True,
        "plots": False,
        "resume": False,
        "pretrained": True,
        "freeze": None,
        "time": None,
        "compile": False,
        "rect": False,
        "close_mosaic": 0,
        "augmentations": [],
        "auto_augment": None,
        "conf": 0.001,
        "iou": 0.7,
        "max_det": 300,
    }
    for key in (
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
    ):
        overrides[key] = 0.0
    return vars(get_cfg(overrides=overrides))


def tensor_hash(value):
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(
        str((array.shape, array.dtype)).encode() + array.tobytes()
    ).hexdigest()


def state_hashes(model):
    return {key: tensor_hash(value) for key, value in model.state_dict().items()}


def freeze(path):
    if path.exists():
        raise ValueError("Preserve previous freeze")
    torch, ultralytics = sdk()
    from ultralytics import YOLO
    from ultralytics.cfg import get_cfg
    from ultralytics.data import YOLODataset
    from ultralytics.nn.tasks import DetectionModel

    manifest = data()
    args = arguments()
    torch.manual_seed(17)
    pretrained = YOLO(str(MODEL)).model
    config = copy.deepcopy(pretrained.yaml)
    model = DetectionModel(copy.deepcopy(config), nc=2, ch=3, verbose=False).float()
    model.load(pretrained, verbose=False)
    torch.save(model.state_dict(), CACHE / "initial.pt")
    dataset = YOLODataset(
        img_path=str(CACHE / "dataset/train.txt"),
        imgsz=1280,
        batch_size=2,
        augment=True,
        hyp=get_cfg(overrides=args),
        data={"names": {0: "head", 1: "ear_tag"}, "nc": 2, "channels": 3},
    )
    counts = []
    for index in range(len(dataset)):
        sample = dataset[index]
        classes = sample["cls"].flatten().tolist()
        counts.append({"head": classes.count(0), "tag": classes.count(1)})
    if sum(r["head"] for r in counts) != 25 or sum(r["tag"] for r in counts) != 42:
        raise ValueError("Native no-augmentation pipeline dropped reviewed instances")
    files = {
        Path(__file__),
        Path(__file__).with_name("test_eartag_localization_training.py"),
        ROI,
        RESULTS / "ownership-training-batch1-v2.json",
        MODEL,
        CACHE / "data-manifest.json",
        CACHE / "initial.pt",
        ROOT / "research/cow_identity/yolo_training_numerics_protocol.json",
        RESULTS / "yolo-training-numerics.json",
    }
    files.update((CACHE / "dataset").rglob("*"))
    files.update(ROOT / r["image"] for r in json.loads(ROI.read_text())["rows"])
    sdkroot = Path(ultralytics.__file__).parent
    files.update(sdkroot.rglob("*.py"))
    files.update(sdkroot.rglob("*.yaml"))
    write(
        path,
        {
            "status": "FROZEN_BEFORE_TRAINING",
            "python": sys.version,
            "files": {str(p): digest(p) for p in sorted(files) if p.is_file()},
            "libraries": {
                n: importlib.metadata.version(n)
                for n in (
                    "torch",
                    "torchvision",
                    "ultralytics",
                    "numpy",
                    "pillow",
                    "opencv-python",
                    "psutil",
                )
            },
            "arguments": args,
            "config": config,
            "initial_state_hashes": state_hashes(model),
            "data": manifest,
            "native_pipeline_counts": counts,
            "limits": {"seconds": 600, "rss_bytes": LIMIT, "mps_driver_bytes": LIMIT},
            "selection": "Exactly epoch20 final EMA via native last.pt, never best.pt. Native training/EMA/validation FP32 with AMP disabled; native checkpoint serialization and stripping use FP16. Subsequent inference explicitly FP32 cannot restore serialization precision. Native best revalidation uses only identical training13crops and is not selection evidence.",
            "native_details": "No custom trainer/optimizer/loss/augmentation methods. Native validation batch4 and rectangular batches, native training shuffle/batch2 including final1sample,140updates with nbs2/no warmup. AdamW beta1=.937/beta2=.999, gradient clip10, constantLR1e-4; native DFL fixed, other layers train. All actual defaults bound. Explicit empty Albumentations list plus scalar zeros. Resource limit aborts without retry/selection.",
            "scope": "13 AI-reviewed training-source ROIs only,25 heads/42 tags; no lowres development or outdoor inputs. No OCR or body ownership evaluation. Training re-use validation is not held-out accuracy. Three-class18wholeframe proposal never run.",
        },
    )


def checked(path):
    document = json.loads(path.read_text())
    if document["python"] != sys.version:
        raise ValueError("Interpreter changed")
    for name, expected in document["files"].items():
        if digest(name) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    for name, version in document["libraries"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError(f"Library changed: {name}")
    return document


class Guard:
    def __init__(self, output, protocol):
        self.output, self.protocol = output, protocol
        self.started = time.monotonic()
        self.peak_rss = self.peak_driver = 0
        self.mps = False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.watch, daemon=True)

    def watch(self):
        import psutil
        import torch

        while not self.stop.wait(0.1):
            self.peak_rss = max(self.peak_rss, psutil.Process().memory_info().rss)
            if self.mps:
                self.peak_driver = max(
                    self.peak_driver, torch.mps.driver_allocated_memory()
                )
            if (
                max(self.peak_rss, self.peak_driver) > LIMIT
                or time.monotonic() - self.started >= 600
            ):
                write(
                    self.output,
                    {
                        "status": "STOPPED_RESOURCE_OR_TIME_LIMIT",
                        "protocol_sha256": digest(self.protocol),
                        **self.stats(),
                    },
                )
                os._exit(77)

    def stats(self):
        return {
            "elapsed_seconds": time.monotonic() - self.started,
            "peak_rss_bytes": self.peak_rss,
            "peak_mps_driver_bytes": self.peak_driver,
        }


class TrainingAudit:
    """Passive native callbacks: reject drift/recovery, never change learning."""

    def __init__(self, document):
        self.document = document
        self.history, self.saved = [], []
        self.batches = 0

    def preflight(self, trainer):
        if (
            trainer.device.type != "mps"
            or trainer.amp
            or trainer.accumulate != 1
            or trainer.batch_size != 2
            or len(trainer.train_loader) != 7
        ):
            raise ValueError("Actual device/precision/batching differs")
        if state_hashes(trainer.model) != self.document["initial_state_hashes"]:
            raise ValueError("Native initialized state differs")
        expected = {row["image"] for row in self.document["data"]["rows"]}
        for loader in (trainer.train_loader, trainer.test_loader):
            if set(loader.dataset.im_files) != expected:
                raise ValueError("Unexpected training/validation source")

    def batch_end(self, trainer):
        import torch

        if (
            not torch.isfinite(trainer.loss_items).all()
            or not torch.isfinite(trainer.loss).all()
        ):
            raise ValueError("Nonfinite native loss: stop instead of recovery")
        self.batches += 1

    def epoch_end(self, trainer):
        if trainer.epoch != len(self.history):
            raise ValueError("Unexpected repeated/skipped epoch")
        self.history.append(
            {
                "epoch": trainer.epoch + 1,
                "loss": trainer.tloss.detach().cpu().tolist(),
                "ema_updates": trainer.ema.updates,
            }
        )
        print(json.dumps(self.history[-1]), flush=True)

    def saved_model(self, trainer):
        self.saved.append({"epoch": trainer.epoch + 1, "sha256": digest(trainer.last)})

    def bind(self, trainer):
        for name, callback in (
            ("on_pretrain_routine_end", self.preflight),
            ("on_train_batch_end", self.batch_end),
            ("on_train_epoch_end", self.epoch_end),
            ("on_model_save", self.saved_model),
        ):
            trainer.add_callback(name, callback)

    def final(self, trainer):
        import torch

        if (
            len(self.history) != 20
            or self.batches != 140
            or trainer.ema.updates != 140
            or not self.saved
            or self.saved[-1]["epoch"] != 20
        ):
            raise ValueError("Incomplete or recovered training is ineligible")
        checkpoint = torch.load(trainer.last, map_location="cpu", weights_only=False)
        final = checkpoint["model"]  # native strip_optimizer moves EMA to model
        if not all(torch.isfinite(v).all() for v in final.state_dict().values()):
            raise ValueError("Final saved EMA contains nonfinite tensors")
        expected = copy.deepcopy(trainer.ema.ema).cpu().half()
        if state_hashes(final) != state_hashes(expected):
            raise ValueError("last.pt differs from final epoch20 EMA")
        return {
            "history": self.history,
            "batches": self.batches,
            "saved": self.saved,
            "selected_checkpoint": str(trainer.last),
            "selected_sha256": digest(trainer.last),
            "stored_float_dtypes": sorted(
                {
                    str(v.dtype)
                    for v in final.state_dict().values()
                    if v.is_floating_point()
                }
            ),
        }


def evaluate_last(path, document):
    from ultralytics import YOLO

    model = YOLO(str(path))
    precision = []

    def verify(validator):
        if validator.device.type != "mps" or validator.args.quantize is not None:
            raise ValueError("Selected final EMA validation must use MPS FP32")
        precision.append(
            {"device": str(validator.device), "quantize": validator.args.quantize}
        )

    model.add_callback("on_val_start", verify)
    result = model.val(
        data=document["arguments"]["data"],
        device="mps",
        imgsz=1280,
        batch=2,
        quantize=32,
        conf=0.001,
        iou=0.7,
        max_det=300,
        plots=False,
        workers=0,
        project=str(CACHE),
        name="last-validation",
        exist_ok=False,
        verbose=False,
    )
    return {"training_only_metrics": result.results_dict, "actual_precision": precision}


def run(protocol, output):
    document = checked(protocol)
    if output.exists() or (CACHE / "run").exists():
        raise ValueError("Preserve prior run/output")
    torch, _ = sdk()
    from ultralytics.models.yolo.detect import DetectionTrainer
    from ultralytics.nn.tasks import DetectionModel

    guard, audit = Guard(output, protocol), TrainingAudit(document)
    guard.thread.start()
    try:
        trainer = DetectionTrainer(overrides=copy.deepcopy(document["arguments"]))
        model = DetectionModel(
            copy.deepcopy(document["config"]), nc=2, ch=3, verbose=False
        ).float()
        model.load_state_dict(
            torch.load(CACHE / "initial.pt", weights_only=True, map_location="cpu"),
            strict=True,
        )
        trainer.model = model
        audit.bind(trainer)
        guard.mps = True
        trainer.train()
        result = audit.final(trainer)
        result.update(evaluate_last(trainer.last, document))
        result.update(
            {
                "status": "COMPLETE_FIXED_TRAINING_ONLY",
                "protocol_sha256": digest(protocol),
                "selection": document["selection"],
                "scope": document["scope"],
                **guard.stats(),
            }
        )
        write(output, result)
    except Exception as error:
        write(
            output,
            {
                "status": "FAILED",
                "protocol_sha256": digest(protocol),
                "error": f"{type(error).__name__}: {error}",
                "history": audit.history,
                "batches": audit.batches,
                **guard.stats(),
            },
        )
        raise
    finally:
        guard.stop.set()
        guard.thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "check", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.protocol)
    elif args.command == "check":
        print(
            json.dumps(
                {"status": "PASS", "files": len(checked(args.protocol)["files"])}
            )
        )
    elif args.output is None:
        parser.error("run requires --output")
    else:
        run(args.protocol, args.output)
