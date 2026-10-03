"""One native OBB training recipe; training-only preflight and fresh final run."""

import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
import threading
import time
from pathlib import Path

from benchmark import digest, write_json
from eartag_obb_data import AUGMENTATION, MODEL, OUTPUT, checked

ROOT = Path(__file__).parent
DATA_PROTOCOL = ROOT / "eartag_obb_data_protocol.json"
CACHE = Path(".cache/cow-ear-tags/obb-training")
LIMIT = 8 * 1024**3


def sdk():
    os.environ["YOLO_CONFIG_DIR"] = str((CACHE / "settings").resolve())
    os.environ["YOLO_OFFLINE"] = "true"
    os.environ["ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS"] = "1"
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


def arguments():
    from ultralytics.cfg import get_cfg

    return vars(
        get_cfg(
            overrides={
                **AUGMENTATION,
                "task": "obb",
                "mode": "train",
                "model": str(MODEL.resolve()),
                "data": str((OUTPUT / "data.yaml").resolve()),
                "device": "mps",
                "imgsz": 320,
                "batch": 16,
                "nbs": 16,
                "epochs": 20,
                "optimizer": "AdamW",
                "lr0": 0.001,
                "lrf": 1.0,
                "weight_decay": 0.0005,
                "warmup_epochs": 0.0,
                "warmup_bias_lr": 0.0,
                "patience": 0,
                "seed": 17,
                "deterministic": True,
                "amp": False,
                "quantize": 32,
                "workers": 0,
                "cache": False,
                "rect": False,
                "val": False,
                "plots": False,
                "save": True,
                "save_period": -1,
                "resume": False,
                "pretrained": True,
                "freeze": None,
                "time": None,
                "compile": False,
                "project": str(CACHE.resolve()),
                "name": "full",
                "exist_ok": False,
            }
        )
    )


def state_hashes(model):
    result = {}
    for key, value in model.state_dict().items():
        array = value.detach().cpu().contiguous().numpy()
        result[key] = hashlib.sha256(
            str((array.shape, array.dtype)).encode() + array.tobytes()
        ).hexdigest()
    return result


def freeze(args):
    from safetensors.torch import save_file

    base = checked(DATA_PROTOCOL)
    manifest_path = OUTPUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not manifest["complete"] or manifest["protocol_sha256"] != digest(DATA_PROTOCOL):
        raise ValueError("Require complete frozen native training data")
    if manifest["native_inventory"]["below_two_pixels"]:
        raise ValueError("Review native tiny-box exclusions before any training")
    torch, _ = sdk()
    from ultralytics import YOLO
    from ultralytics.nn.tasks import OBBModel

    torch.manual_seed(17)
    pretrained = YOLO(str(MODEL)).model
    config = copy.deepcopy(pretrained.yaml)
    model = OBBModel(copy.deepcopy(config), nc=1, ch=3, verbose=False).float()
    model.load(pretrained, verbose=False)
    CACHE.mkdir(parents=True, exist_ok=True)
    initial = CACHE / "initial.safetensors"
    if initial.exists():
        raise ValueError("Preserve fixed initialization")
    save_file(
        {
            key: value.detach().cpu().contiguous().clone()
            for key, value in model.state_dict().items()
        },
        initial,
    )
    files = [
        Path(__file__),
        ROOT / "test_eartag_obb_training.py",
        DATA_PROTOCOL,
        manifest_path,
        Path(manifest["data_yaml"]),
        initial,
    ]
    files.extend(
        Path(row[key]) for row in manifest["rows"] for key in ("image", "label")
    )
    write_json(
        args.protocol,
        {
            "scope": "One predeclared native YOLO11n OBB text-line adaptation. Same 1347 training tag images/3243 polygons. No pilot, calibration or reserved images during training, timing or native validation. Final epoch20 last.pt only, not best.pt; no threshold/model/epoch search.",
            "files": {**base["files"], **{str(path): digest(path) for path in files}},
            "libraries": {
                **base["libraries"],
                **{
                    name: importlib.metadata.version(name)
                    for name in ("safetensors", "psutil")
                },
            },
            "arguments": arguments(),
            "config": config,
            "initial_state_hashes": state_hashes(model),
            "initial_weights": str(initial),
            "data_manifest": str(manifest_path),
            "expected_batches_per_epoch": 85,
            "expected_final_steps": 1700,
            "preflight": {
                "optimizer_steps": 20,
                "maximum_seconds": 180,
                "maximum_projected_full_seconds": 720,
                "projection": "Elapsed setup plus 1700 times mean batch duration after first two steps, plus 30 seconds reserved for native final training-only validations and serialization. Fresh initial checkpoint and optimizer for the subsequent full run.",
            },
            "limits": {
                "full_seconds": 900,
                "rss_bytes": LIMIT,
                "mps_driver_bytes": LIMIT,
            },
            "checkpoint": "Native last.pt final EMA, which the SDK serializes/strips in FP16 even though training is FP32. Later explicit FP32 inference cannot restore serialization precision. Verify saved state equals final live EMA cast to FP16. SDK best.pt validation sees identical training images only; best.pt is ignored for study selection.",
            "native": "Native OBBTrainer, dataloader, optimizer, criterion, EMA and final validation. Passive public callbacks and optimizer hooks only; no replacement training loop. No AMP, workers0, nbs16 makes one optimizer update per batch16; incomplete last batch3 included. Native AdamW beta1=.937/beta2=.999 and clip10 remain unchanged. Empty Albumentations list and all scalar augmentation controls zero.",
            "evaluation": "Separate evaluation will be frozen before pilot predictions. Original native quadrilaterals remain scoring truth; OBB minimum-area rectangles are a representational limitation. No reader score can retrospectively change this training recipe.",
        },
    )


def validate(path):
    value = json.loads(path.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen OBB training input changed: {name}")
    if {name: importlib.metadata.version(name) for name in value["libraries"]} != value[
        "libraries"
    ]:
        raise ValueError("Training environment changed")
    return value


def eligible_final(history, steps, expected=1700):
    if (
        len(history) != 20
        or [row["epoch"] for row in history] != list(range(1, 21))
        or steps != expected
    ):
        raise ValueError("Require all original final epochs and optimizer updates")


class PreflightComplete(Exception):
    """Stop only after the complete twentieth native batch/EMA update."""


class Guard:
    def __init__(self, output, protocol, seconds):
        self.output, self.protocol, self.seconds = output, protocol, seconds
        self.started = time.perf_counter()
        self.peak_rss = self.peak_driver = 0
        self.active_mps = False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.watch, daemon=True)

    def watch(self):
        import psutil
        import torch

        while not self.stop.wait(0.1):
            self.peak_rss = max(self.peak_rss, psutil.Process().memory_info().rss)
            if self.active_mps:
                self.peak_driver = max(
                    self.peak_driver, torch.mps.driver_allocated_memory()
                )
            if (
                max(self.peak_rss, self.peak_driver) > LIMIT
                or time.perf_counter() - self.started > self.seconds
            ):
                write_json(
                    self.output,
                    {
                        "complete": False,
                        "error": "Fixed resource/time budget exceeded; no retry",
                        "protocol_sha256": digest(self.protocol),
                        **self.stats(),
                    },
                )
                os._exit(77)

    def stats(self):
        return {
            "elapsed_seconds": time.perf_counter() - self.started,
            "peak_rss_bytes": self.peak_rss,
            "peak_driver_bytes": self.peak_driver,
        }


class Audit:
    def __init__(self, frozen, preflight):
        self.frozen, self.preflight = frozen, preflight
        self.steps, self.batches, self.history = 0, [], []
        self.tick = 0.0
        self.handles = []

    def ready(self, trainer):
        if (
            trainer.device.type != "mps"
            or trainer.amp
            or trainer.accumulate != 1
            or trainer.batch_size != 16
            or len(trainer.train_loader) != 85
        ):
            raise ValueError("Native device/precision/batching drift")
        if state_hashes(trainer.model) != self.frozen["initial_state_hashes"]:
            raise ValueError(
                "Native model must start at the original frozen initialization"
            )
        data = json.loads(Path(self.frozen["data_manifest"]).read_text())
        expected = {str(Path(row["image"]).resolve()) for row in data["rows"]}
        for loader in (trainer.train_loader, trainer.test_loader):
            if {str(Path(p).resolve()) for p in loader.dataset.im_files} != expected:
                raise ValueError("Training-only validation/source set changed")
        self.handles.append(trainer.optimizer.register_step_pre_hook(self.before_step))
        self.handles.append(trainer.optimizer.register_step_post_hook(self.after_step))

    def before_step(self, optimizer, _args, _kwargs):
        import torch

        finite = [
            torch.isfinite(p.grad).all()
            for group in optimizer.param_groups
            for p in group["params"]
            if p.grad is not None
        ]
        if not torch.stack(finite).all():
            raise ValueError("Nonfinite native gradient; stop without recovery")

    def after_step(self, _optimizer, _args, _kwargs):
        self.steps += 1

    def batch_start(self, _trainer):
        self.tick = time.perf_counter()

    def batch_end(self, trainer):
        import torch

        torch.mps.synchronize()
        if (
            not torch.isfinite(trainer.loss_items).all()
            or not torch.isfinite(trainer.loss).all()
        ):
            raise ValueError("Nonfinite native loss; no recovery")
        if self.steps != len(self.batches) + 1 or trainer.ema.updates != self.steps:
            raise ValueError(
                "Every frozen batch must complete exactly one optimizer and EMA update"
            )
        self.batches.append(
            {
                "step": self.steps,
                "epoch": trainer.epoch + 1,
                "loss": trainer.loss_items.detach().cpu().tolist(),
                "seconds": time.perf_counter() - self.tick,
            }
        )
        if self.steps % 10 == 0:
            print(json.dumps(self.batches[-1]), flush=True)
        if self.preflight and self.steps == 20:
            raise PreflightComplete

    def epoch_end(self, trainer):
        if trainer.epoch != len(self.history):
            raise ValueError("Repeated/skipped native epoch")
        self.history.append(
            {
                "epoch": trainer.epoch + 1,
                "loss": trainer.tloss.detach().cpu().tolist(),
                "ema_updates": trainer.ema.updates,
            }
        )

    def bind(self, trainer):
        for name, function in (
            ("on_pretrain_routine_end", self.ready),
            ("on_train_batch_start", self.batch_start),
            ("on_train_batch_end", self.batch_end),
            ("on_train_epoch_end", self.epoch_end),
        ):
            trainer.add_callback(name, function)

    def final(self, trainer):
        import torch

        eligible_final(self.history, self.steps)
        checkpoint = torch.load(trainer.last, map_location="cpu", weights_only=False)
        saved = checkpoint["model"]
        expected = copy.deepcopy(trainer.ema.ema).cpu().half()
        if state_hashes(saved) != state_hashes(expected):
            raise ValueError("Native last.pt is not exactly final epoch20 EMA")
        if not all(
            torch.isfinite(value).all() for value in saved.state_dict().values()
        ):
            raise ValueError("Final saved model is nonfinite")
        return {
            "checkpoint": str(trainer.last),
            "checkpoint_sha256": digest(trainer.last),
            "stored_float_dtypes": sorted(
                {
                    str(v.dtype)
                    for v in saved.state_dict().values()
                    if v.is_floating_point()
                }
            ),
        }


def run(args):
    from safetensors.torch import load_file

    frozen = validate(args.protocol)
    torch, _ = sdk()
    from ultralytics.models.yolo.obb import OBBTrainer
    from ultralytics.nn.tasks import OBBModel

    if not torch.backends.mps.is_available():
        raise RuntimeError("Actual MPS required")
    report = {
        "protocol_sha256": digest(args.protocol),
        "mode": args.mode,
        "complete": False,
        "error": None,
        "actual_device": "mps",
        "training_precision": "float32",
    }
    limit = 180 if args.mode == "preflight" else 900
    guard, audit = (
        Guard(args.output, args.protocol, limit),
        Audit(frozen, args.mode == "preflight"),
    )
    guard.thread.start()
    try:
        native_args = copy.deepcopy(frozen["arguments"])
        native_args["name"] = args.mode
        if (Path(native_args["project"]) / args.mode).exists():
            raise ValueError("Preserve previous native training run")
        trainer = OBBTrainer(overrides=native_args)
        trainer.model = OBBModel(
            copy.deepcopy(frozen["config"]), nc=1, ch=3, verbose=False
        ).float()
        trainer.model.load_state_dict(
            load_file(frozen["initial_weights"], device="cpu"), strict=True
        )
        audit.bind(trainer)
        guard.active_mps = True
        trainer.train()
        report.update(audit.final(trainer))
        report["complete"] = True
    except PreflightComplete:
        report["complete"] = True
        mean = sum(row["seconds"] for row in audit.batches[2:]) / 18
        setup = (
            time.perf_counter()
            - guard.started
            - sum(row["seconds"] for row in audit.batches)
        )
        report["projected_full_seconds"] = setup + 1700 * mean + 30
        report["projection_within_twelve_minutes"] = (
            report["projected_full_seconds"] <= 720
        )
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        guard.stop.set()
        guard.thread.join()
        for handle in audit.handles:
            handle.remove()
        report.update(
            guard.stats(),
            steps=audit.steps,
            batches=audit.batches,
            history=audit.history,
        )
        write_json(args.output, report)
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in ("batches", "history")}
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "preflight", "train"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Use new immutable paths")
    (freeze if args.mode == "freeze" else run)(args)
