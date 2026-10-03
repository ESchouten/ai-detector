"""One native YOLO11s CPU/MPS forward/backward comparison, without an optimizer."""

import argparse
import copy
import gc
import hashlib
import importlib.metadata
import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import torch
import ultralytics
from benchmark import digest, write_json
from ultralytics import YOLO
from ultralytics.nn.tasks import DetectionModel
from ultralytics.utils import DEFAULT_CFG

ROOT = Path(__file__).parent
MODEL = Path(".cache/cow-video-policy-cache/yolo11s.pt")
MODEL_SHA256 = "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5"
CACHE = Path(".cache/cow-yolo-training-numerics")
SEED = 17


def tensor_hash(value):
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(
        str((array.shape, array.dtype)).encode() + array.tobytes()
    ).hexdigest()


def flatten(value, prefix=""):
    if isinstance(value, torch.Tensor):
        return {prefix: value}
    if isinstance(value, dict):
        return {
            k: v
            for name, child in value.items()
            for k, v in flatten(child, f"{prefix}.{name}").items()
        }
    if isinstance(value, (tuple, list)):
        return {
            k: v
            for index, child in enumerate(value)
            for k, v in flatten(child, f"{prefix}.{index}").items()
        }
    raise ValueError(f"Unexpected model output: {type(value)}")


def compare(left, right):
    if left is None or right is None:
        return {
            "missing_cpu": left is None,
            "missing_mps": right is None,
            "both_missing": left is None and right is None,
        }
    assert left.shape == right.shape
    a, b = (
        left.detach().cpu().double().flatten(),
        right.detach().cpu().double().flatten(),
    )
    finite = bool(torch.isfinite(a).all() and torch.isfinite(b).all())
    if not finite:
        return {"finite": False, "shape": list(left.shape)}
    difference = a - b
    norm = float(torch.linalg.vector_norm(a))
    error = float(torch.linalg.vector_norm(difference))
    return {
        "shape": list(left.shape),
        "finite": True,
        "cpu_norm": norm,
        "mps_norm": float(torch.linalg.vector_norm(b)),
        "relative_l2": error / norm if norm else (0.0 if error == 0 else None),
        "l2_difference": error,
        "maximum_absolute_difference": float(difference.abs().max()) if len(a) else 0,
        "different_elements": int(torch.count_nonzero(difference)),
        "exact": torch.equal(left, right),
    }


def make_model(config, state):
    torch.manual_seed(SEED)
    model = DetectionModel(copy.deepcopy(config), nc=3, verbose=False).float().train()
    model.load_state_dict(state, strict=True)
    model.args = copy.deepcopy(DEFAULT_CFG)
    for module in model.modules():
        if isinstance(module, torch.nn.Dropout):
            module.p = 0
    return model


def freeze(path):
    if digest(MODEL) != MODEL_SHA256:
        raise ValueError("Official cached YOLO11s checkpoint differs")
    if CACHE.exists():
        raise ValueError("Preserve prior initialized inputs")
    CACHE.mkdir(parents=True)
    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    pretrained = YOLO(str(MODEL)).model
    assert len(pretrained.names) == 80
    config = copy.deepcopy(pretrained.yaml)
    model = DetectionModel(copy.deepcopy(config), nc=3, verbose=False).float().train()
    model.load(pretrained, verbose=False)
    state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    torch.save(state, CACHE / "initial.pt")
    rng = np.random.default_rng(SEED)
    batch = {
        "img": torch.from_numpy(rng.random((2, 3, 1280, 1280), dtype=np.float32)),
        "batch_idx": torch.tensor([0, 0, 0, 1, 1, 1], dtype=torch.float32),
        "cls": torch.tensor([[0], [1], [2], [0], [1], [2]], dtype=torch.float32),
        "bboxes": torch.tensor(
            [
                [0.23, 0.24, 0.03, 0.025],
                [0.29, 0.35, 0.15, 0.13],
                [0.51, 0.56, 0.63, 0.70],
                [0.76, 0.31, 0.035, 0.028],
                [0.68, 0.40, 0.17, 0.14],
                [0.48, 0.53, 0.68, 0.72],
            ],
            dtype=torch.float32,
        ),
    }
    torch.save(batch, CACHE / "batch.pt")
    sdk = Path(ultralytics.__file__).parent
    files = {
        Path(__file__),
        ROOT / "test_yolo_training_numerics.py",
        ROOT / "benchmark.py",
        MODEL,
        CACHE / "initial.pt",
        CACHE / "batch.pt",
    }
    files.update(sdk.rglob("*.py"))
    files.add(sdk / "cfg/default.yaml")
    write_json(
        path,
        {
            "status": "FROZEN_BEFORE_1280_FORWARD_BACKWARD",
            "files": {str(p): digest(p) for p in sorted(files)},
            "libraries": {
                n: importlib.metadata.version(n)
                for n in ("torch", "ultralytics", "numpy", "psutil")
            },
            "model_config": config,
            "initial_state_hashes": {k: tensor_hash(v) for k, v in state.items()},
            "input_hashes": {k: tensor_hash(v) for k, v in batch.items()},
            "recipe": {
                "seed": SEED,
                "batch": 2,
                "imgsz": 1280,
                "classes": 3,
                "precision": "float32",
                "torch_threads": 2,
                "runs": ["cpu", "mps"],
                "training_mode": "native train, including batch normalization; dropout disabled; no augmentation; one forward and native loss/backward, no optimizer",
                "weight_initialization": "Official cached COCO YOLO11s intersected into a fresh3-class DetectionModel; unmatched classifier tensors deterministicseed17. Full resulting initialized state frozen, restored identically before each device.",
                "loss": "model(img), model.loss(batch,preds=output); sum returned batch-scaled box/cls/dfl vector for backward. Passive public forward hook records native task-aligned assigner outputs.",
                "maximum_seconds": 180,
                "maximum_rss_bytes": 8 * 1024**3,
                "maximum_driver_bytes": 8 * 1024**3,
                "comparison": "Every native output/feature, three native loss components, all named parameter gradient arrays/norms and batch-normalization buffers. CPU FP64 reductions compare arrays. No fitted threshold or accuracy claim.",
            },
            "limitations": "One synthetic batch is not a certificate for all operators, sizes, batches, optimizer steps or training. Discrete task-aligned assignments can differ from tiny forward roundoff; gradient divergence alone does not prove an MPS arithmetic defect. No real development/evaluation frames or biological labels.",
        },
    )


def checked(path):
    value = json.loads(path.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen numerical input changed: {name}")
    assert value["libraries"] == {
        name: importlib.metadata.version(name) for name in value["libraries"]
    }
    return value


class Monitor:
    def __init__(self, output, protocol):
        self.output, self.protocol = output, protocol
        self.stop = threading.Event()
        self.mps = False
        self.peak_rss = self.peak_driver = 0
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self.watch, daemon=True)

    def watch(self):
        while not self.stop.wait(0.05):
            self.peak_rss = max(self.peak_rss, psutil.Process().memory_info().rss)
            if self.mps:
                self.peak_driver = max(
                    self.peak_driver, torch.mps.driver_allocated_memory()
                )
            reason = (
                "resource_bound"
                if max(self.peak_rss, self.peak_driver) > 8 * 1024**3
                else "time_bound"
                if time.monotonic() - self.started > 175
                else None
            )
            if reason:
                write_json(
                    self.output,
                    {
                        "status": "STOPPED",
                        "reason": reason,
                        "protocol_sha256": digest(self.protocol),
                        "peak_rss_bytes": self.peak_rss,
                        "peak_driver_bytes": self.peak_driver,
                    },
                )
                os._exit(77)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()


def run_one(device, protocol, monitor):
    state = torch.load(CACHE / "initial.pt", map_location="cpu", weights_only=True)
    model = make_model(protocol["model_config"], state).to(device)
    assert {k: tensor_hash(v) for k, v in model.state_dict().items()} == protocol[
        "initial_state_hashes"
    ]
    batch = {
        k: v.to(device)
        for k, v in torch.load(
            CACHE / "batch.pt", map_location="cpu", weights_only=True
        ).items()
    }
    assert {k: tensor_hash(v) for k, v in batch.items()} == protocol["input_hashes"]
    torch.manual_seed(SEED)
    if device == "mps":
        torch.mps.manual_seed(SEED)
        monitor.mps = True
    model.criterion = model.init_criterion()
    assigned = {}

    def record_assignment(module, inputs, result):
        assigned.update(
            {k: v.detach().cpu().clone() for k, v in flatten(result).items()}
        )

    handle = model.criterion.assigner.register_forward_hook(record_assignment)
    model.zero_grad(set_to_none=True)
    start = time.perf_counter()
    outputs = model(batch["img"])
    losses, components = model.loss(batch, preds=outputs)
    detached = {k: v.detach().cpu().clone() for k, v in flatten(outputs).items()}
    forward = time.perf_counter() - start
    print(
        json.dumps(
            {
                "device": device,
                "phase": "forward",
                "seconds": forward,
                "components": components.detach().cpu().tolist(),
            }
        ),
        flush=True,
    )
    losses.sum().backward()
    if device == "mps":
        torch.mps.synchronize()
    result = {
        "device": str(next(model.parameters()).device),
        "dtype": str(next(model.parameters()).dtype),
        "forward_seconds": forward,
        "total_seconds": time.perf_counter() - start,
        "initial_state_and_inputs_exact": True,
        "outputs": detached,
        "losses": losses.detach().cpu().clone(),
        "components": components.detach().cpu().clone(),
        "assignment": assigned,
        "gradients": {
            k: None if p.grad is None else p.grad.detach().cpu().clone()
            for k, p in model.named_parameters()
        },
        "buffers": {k: v.detach().cpu().clone() for k, v in model.named_buffers()},
    }
    handle.remove()
    torch.save(result, CACHE / f"{device}.pt")
    del outputs, losses, components, model, batch, state
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()
    print(
        json.dumps(
            {"device": device, "phase": "complete", "seconds": result["total_seconds"]}
        ),
        flush=True,
    )
    return result


def assess(cpu, metal):
    result = {}
    for category in ("outputs", "gradients", "assignment", "buffers"):
        assert cpu[category].keys() == metal[category].keys()
        result[category] = {
            k: compare(v, metal[category][k]) for k, v in cpu[category].items()
        }
    result["losses"] = compare(cpu["losses"], metal["losses"])
    result["components"] = compare(cpu["components"], metal["components"])
    result["component_values"] = {
        "order": ["box", "cls", "dfl"],
        "cpu": cpu["components"].tolist(),
        "mps": metal["components"].tolist(),
    }
    gradients = result["gradients"]
    finite = (
        all(
            v.get("finite", v.get("both_missing", False))
            for cat in ("outputs", "gradients", "assignment", "buffers")
            for v in result[cat].values()
        )
        and result["losses"]["finite"]
        and result["components"]["finite"]
    )
    relative = [
        (v["relative_l2"], k)
        for k, v in gradients.items()
        if v.get("relative_l2") is not None
    ]
    result["summary"] = {
        "finite_and_matching_presence": finite,
        "parameter_tensors": len(gradients),
        "with_gradients": sum("finite" in v for v in gradients.values()),
        "maximum_gradient_relative_l2": max(relative),
        "maximum_output_relative_l2": max(
            v["relative_l2"] for v in result["outputs"].values()
        ),
        "zero_cpu_nonzero_mps_gradients": [
            k
            for k, v in gradients.items()
            if v.get("cpu_norm") == 0 and v.get("mps_norm", 0) > 0
        ],
        "foreground_assignment_exact": result["assignment"][".3"]["exact"],
        "target_index_exact": result["assignment"][".4"]["exact"],
    }
    return result


def run(path, output):
    value = checked(path)
    torch.set_num_threads(2)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Real MPS required")
    report = {"status": "INCOMPLETE", "protocol_sha256": digest(path)}
    with Monitor(output, path) as monitor:
        try:
            cpu = run_one("cpu", value, monitor)
            metal = run_one("mps", value, monitor)
            report.update(
                status="COMPLETE_DIAGNOSTIC",
                comparison=assess(cpu, metal),
                devices={
                    name: {
                        k: value[k]
                        for k in (
                            "device",
                            "dtype",
                            "forward_seconds",
                            "total_seconds",
                            "initial_state_and_inputs_exact",
                        )
                    }
                    for name, value in [("cpu", cpu), ("mps", metal)]
                },
                artifacts={
                    str(CACHE / f"{name}.pt"): digest(CACHE / f"{name}.pt")
                    for name in ("cpu", "mps")
                },
            )
        except BaseException as error:
            report.update(status="FAILED", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            report.update(
                elapsed_seconds=time.monotonic() - monitor.started,
                peak_rss_bytes=monitor.peak_rss,
                peak_driver_bytes=monitor.peak_driver,
            )
            write_json(output, report)
    print(
        json.dumps({"status": report["status"], **report["comparison"]["summary"]}),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "check", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            parser.error("Preserve frozen diagnostic")
        freeze(args.protocol)
    elif args.mode == "check":
        print(json.dumps({"files": len(checked(args.protocol)["files"])}))
    else:
        run(args.protocol, args.output)
