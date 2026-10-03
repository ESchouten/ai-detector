"""Frozen training-only CPU/MPS backward consistency diagnosis, no retraining."""

import argparse
import gc
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from eartag_trocr import (
    DATA,
    MODEL,
    RECIPE,
    checked,
    encode_labels,
    epoch_indices,
    load_model,
    optimizer_groups,
    pixels,
    processor,
)

ROOT = Path(__file__).parent
BASE = ROOT / "eartag_trocr_protocol.json"
PREVIOUS = ROOT / "results/2026-10-03/ear-tags/trocr-fresh-reset-audit.json"


def array_hash(array):
    return hashlib.sha256(
        str((array.shape, str(array.dtype))).encode() + array.tobytes()
    ).hexdigest()


def compare_tensor(left, right):
    a, b = left.float().flatten(), right.float().flatten()
    if a.shape != b.shape or not torch.isfinite(a).all() or not torch.isfinite(b).all():
        raise ValueError("Compare finite matching gradient/parameter shapes only")
    delta = a - b
    norm = float(torch.linalg.vector_norm(a.double()))
    error = float(torch.linalg.vector_norm(delta.double()))
    return {
        "maximum_absolute_difference": float(delta.abs().max())
        if delta.numel()
        else 0.0,
        "l2_difference": error,
        "left_l2": norm,
        "right_l2": float(torch.linalg.vector_norm(b.double())),
        "relative_l2_difference": error / norm if norm else None,
        "exact": torch.equal(a, b),
    }


def freeze(args):
    base = checked(BASE)
    data = json.loads(DATA.read_text())
    rows = data["panels"]["train"]
    indices = optimizer_groups(epoch_indices(len(rows), RECIPE["seed"], 0), 4, 2)[0]
    processing = processor()
    arrays, inputs = {}, []
    for number, group in enumerate(indices):
        selected = [rows[index] for index in group]
        arrays[f"pixels{number}"] = pixels(processing, selected).numpy()
        arrays[f"labels{number}"] = encode_labels(
            processing.tokenizer, [row["text"] for row in selected]
        ).numpy()
        inputs.append(
            {
                "indices": group,
                "crops": [
                    {"id": row["id"], "index": row["index"], "sha256": row["sha256"]}
                    for row in selected
                ],
                "pixels_sha256": array_hash(arrays[f"pixels{number}"]),
                "labels_sha256": array_hash(arrays[f"labels{number}"]),
            }
        )
    args.inputs.parent.mkdir(parents=True, exist_ok=True)
    with args.inputs.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    paths = [
        Path(__file__),
        ROOT / "test_eartag_trocr_backward.py",
        BASE,
        PREVIOUS,
        args.inputs,
    ]
    write_json(
        args.protocol,
        {
            "scope": "Single first-training-batch numerical diagnostic, not accuracy or retraining. No pilot/calibration/reserved images. Compare CPU then two fresh MPS passes; no parameter/model search.",
            "files": {**base["files"], **{str(path): digest(path) for path in paths}},
            "base_protocol_sha256": digest(BASE),
            "libraries": base["libraries"],
            "inputs": str(args.inputs),
            "batches": inputs,
            "recipe": {
                "seed": RECIPE["seed"],
                "runs": ["cpu", "mps", "mps"],
                "mode": "eval with gradients enabled (dropout disabled)",
                "precision": "float32",
                "microbatch": 4,
                "accumulation": 2,
                "optimizer": "Fresh AdamW using exact frozen original learning rate/betas/epsilon/weight_decay, clip1.0",
                "gradient_capture": "Every named gradient before clipping, native preclip norm versus CPU FP64 recomputation, gradient after clipping, parameter before/after first optimizer step. Missing gradients retained. CPU reference comparisons and MPS repeat compare full arrays, summarized by layer; no threshold selection.",
                "maximum_seconds": 180,
                "maximum_driver_bytes": 8 * 1024**3,
                "torch_threads": 2,
            },
            "caveat": "Eval-mode dropout-disabled diagnosis differs deliberately from the original train-mode experiment. It can isolate an issue but does not retrospectively certify or repair prior training.",
        },
    )


def validate(path):
    value = json.loads(path.read_text())
    checked(BASE)
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Diagnostic binding changed: {name}")
    return value


def cpu_gradients(model):
    return {
        name: None if p.grad is None else p.grad.detach().cpu().clone()
        for name, p in model.named_parameters()
    }


def norm_on_cpu(gradients):
    return (
        sum(
            float(g.double().square().sum())
            for g in gradients.values()
            if g is not None
        )
        ** 0.5
    )


def elapsed_guard(started):
    if time.perf_counter() - started > 180:
        raise RuntimeError("Three-minute diagnostic limit exceeded")


def run_one(device, arrays, started):
    torch.manual_seed(RECIPE["seed"])
    model = load_model(MODEL, device).eval()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=RECIPE["learning_rate"],
        betas=tuple(RECIPE["betas"]),
        eps=RECIPE["epsilon"],
        weight_decay=RECIPE["weight_decay"],
    )
    before = {name: p.detach().cpu().clone() for name, p in model.named_parameters()}
    losses, logits = [], []
    tick = time.perf_counter()
    optimizer.zero_grad(set_to_none=True)
    for number in range(2):
        image = torch.from_numpy(arrays[f"pixels{number}"].copy()).to(device)
        label = torch.from_numpy(arrays[f"labels{number}"].copy()).to(device)
        result = model(pixel_values=image, labels=label)
        if not torch.isfinite(result.loss) or not torch.isfinite(result.logits).all():
            raise RuntimeError("Nonfinite forward output")
        losses.append(float(result.loss.detach().cpu()))
        logits.append(result.logits.detach().cpu().clone())
        (result.loss / 2).backward()
        del result, image, label
        elapsed_guard(started)
    gradients = cpu_gradients(model)
    cpu_norm = norm_on_cpu(gradients)
    native_norm = float(
        torch.nn.utils.clip_grad_norm_(
            model.parameters(), RECIPE["gradient_clip"], error_if_nonfinite=True
        )
        .detach()
        .cpu()
    )
    clipped = cpu_gradients(model)
    optimizer.step()
    if device == "mps":
        torch.mps.synchronize()
    updates = {
        name: p.detach().cpu().clone() - before[name]
        for name, p in model.named_parameters()
    }
    information = {
        "device": device,
        "mode": "eval, gradients enabled",
        "losses": losses,
        "seconds": time.perf_counter() - tick,
        "native_preclip_global_gradient_norm": native_norm,
        "cpu_fp64_preclip_global_gradient_norm": cpu_norm,
        "cpu_fp64_postclip_global_gradient_norm": norm_on_cpu(clipped),
        "missing_gradients": [
            name for name, value in gradients.items() if value is None
        ],
        "driver_bytes": torch.mps.driver_allocated_memory()
        if device == "mps"
        else None,
        "active_bytes": torch.mps.current_allocated_memory()
        if device == "mps"
        else None,
    }
    if (
        information["driver_bytes"] is not None
        and information["driver_bytes"] > 8 * 1024**3
    ):
        raise RuntimeError("Eight-GiB diagnostic resource limit exceeded")
    elapsed_guard(started)
    del model, optimizer, clipped
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()
    return information, {
        "initial": before,
        "gradients": gradients,
        "updates": updates,
        "logits": logits,
    }


def compare_runs(left, right):
    report = {"layers": {}, "logits": []}
    if left["initial"].keys() != right["initial"].keys():
        raise ValueError("Parameter keys changed")
    for name in left["initial"]:
        a, b = left["gradients"][name], right["gradients"][name]
        if (a is None) != (b is None):
            raise ValueError("Gradient presence changed")
        report["layers"][name] = {
            "initial": compare_tensor(left["initial"][name], right["initial"][name]),
            "gradient": None if a is None else compare_tensor(a, b),
            "update": compare_tensor(left["updates"][name], right["updates"][name]),
        }
    report["logits"] = [
        compare_tensor(a, b)
        for a, b in zip(left["logits"], right["logits"], strict=True)
    ]
    for category in ("initial", "gradient", "update"):
        values = [
            row[category]
            for row in report["layers"].values()
            if row[category] is not None
        ]
        report[category + "_summary"] = {
            "all_exact": all(row["exact"] for row in values),
            "maximum_absolute_difference": max(
                row["maximum_absolute_difference"] for row in values
            ),
            "global_relative_l2_difference": (
                sum(row["l2_difference"] ** 2 for row in values)
                / sum(row["left_l2"] ** 2 for row in values)
            )
            ** 0.5,
        }
    return report


def run(args):
    value = validate(args.protocol)
    if not torch.backends.mps.is_available():
        raise RuntimeError("CPU/MPS comparison requires actual MPS")
    torch.set_num_threads(2)
    archive = np.load(value["inputs"], allow_pickle=False)
    arrays = {key: archive[key] for key in archive.files}
    for i, row in enumerate(value["batches"]):
        if (
            array_hash(arrays[f"pixels{i}"]) != row["pixels_sha256"]
            or array_hash(arrays[f"labels{i}"]) != row["labels_sha256"]
        ):
            raise ValueError("Frozen numeric inputs changed")
    result = {
        "protocol_sha256": digest(args.protocol),
        "complete": False,
        "runs": [],
        "comparisons": {},
        "error": None,
    }
    started = time.perf_counter()
    snapshots = []
    try:
        for device in value["recipe"]["runs"]:
            info, snapshot = run_one(device, arrays, started)
            snapshots.append(snapshot)
            result["runs"].append(info)
            print(json.dumps(info), flush=True)
        for name, left, right in (
            ("cpu_vs_mps_a", 0, 1),
            ("cpu_vs_mps_b", 0, 2),
            ("mps_a_vs_mps_b", 1, 2),
        ):
            result["comparisons"][name] = compare_runs(
                snapshots[left], snapshots[right]
            )
            elapsed_guard(started)
        result["complete"] = True
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        result["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("New protocol/output required")
    if args.mode == "freeze":
        if args.inputs is None or args.inputs.exists():
            parser.error("New input archive required")
        freeze(args)
    else:
        run(args)
