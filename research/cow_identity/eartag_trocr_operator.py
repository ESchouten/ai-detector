"""One actual TrOCR projection/normalization boundary and isolated linear backward."""

import argparse
import gc
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional
from benchmark import digest, write_json
from eartag_trocr import MODEL, RECIPE, load_model
from eartag_trocr_backward import compare_tensor, elapsed_guard, validate
from transformers import modeling_utils
from transformers.loss import loss_utils

ROOT = Path(__file__).parent
BASE = ROOT / "eartag_trocr_backward_protocol.json"


def freeze(args):
    base = validate(BASE)
    paths = [
        Path(__file__),
        ROOT / "test_eartag_trocr_operator.py",
        BASE,
        Path(modeling_utils.__file__),
        Path(loss_utils.__file__),
    ]
    write_json(
        args.protocol,
        {
            "scope": "Training-only first4examples, actual projection/finalLayerNorm forward/backward followed by isolated exact linear operator. No accuracy data, optimizer updates, tuning or retraining.",
            "files": {**base["files"], **{str(p): digest(p) for p in paths}},
            "inputs": base["inputs"],
            "recipe": {
                "first_microbatch": 0,
                "mode": "eval, gradients enabled",
                "seed": RECIPE["seed"],
                "dtype": "float32",
                "device_order": ["cpu", "mps"],
                "boundaries": [
                    "decoder.output_projection",
                    "decoder.model.decoder.layers.5.final_layer_norm",
                ],
                "isolated": [
                    "native3d_explicit_gradient",
                    "native3d_scalar_dot",
                    "flat2d_explicit_gradient",
                    "manual3d_input_gradient",
                    "manual2d_input_gradient",
                ],
                "isolation_inputs": "Same CPU-trace projection input/weight/upstream gradient reused across devices; contiguous copies. Original native tensor strides retained as evidence. CPU float64 direct product is additional numeric reference.",
                "maximum_seconds": 180,
                "threads": 2,
                "maximum_driver_bytes": 8 * 1024**3,
            },
        },
    )


def copied(tensor):
    return tensor.detach().cpu().clone()


def native_trace(device, arrays):
    torch.manual_seed(RECIPE["seed"])
    model = load_model(MODEL, device).eval()
    captured = {}

    def hook(name):
        def record(_module, inputs, output):
            for suffix, tensor in (("input", inputs[0]), ("output", output)):
                tensor.retain_grad()
                captured[name + "_" + suffix] = tensor

        return record

    handles = [
        model.decoder.output_projection.register_forward_hook(hook("projection")),
        model.decoder.model.decoder.layers[-1].final_layer_norm.register_forward_hook(
            hook("normalization")
        ),
    ]
    image = torch.from_numpy(arrays["pixels0"].copy()).to(device)
    labels = torch.from_numpy(arrays["labels0"].copy()).to(device)
    output = model(pixel_values=image, labels=labels)
    output.loss.backward()
    if device == "mps":
        torch.mps.synchronize()
    info = {
        "device": device,
        "loss": float(output.loss.detach().cpu()),
        "boundaries": {},
        "driver_bytes": torch.mps.driver_allocated_memory()
        if device == "mps"
        else None,
    }
    data = {}
    for name, tensor in captured.items():
        if tensor.grad is None:
            raise ValueError("Missing boundary gradient")
        info["boundaries"][name] = {
            "shape": list(tensor.shape),
            "stride": list(tensor.stride()),
            "gradient_stride": list(tensor.grad.stride()),
            "grad_fn": type(tensor.grad_fn).__name__,
        }
        data[name] = copied(tensor)
        data[name + "_gradient"] = copied(tensor.grad)
    data["projection_weight"] = copied(model.decoder.output_projection.weight)
    data["projection_weight_gradient"] = copied(
        model.decoder.output_projection.weight.grad
    )
    data["labels"] = copied(labels)
    if info["driver_bytes"] is not None and info["driver_bytes"] > 8 * 1024**3:
        raise RuntimeError("EightGiB resource cap exceeded")
    for handle in handles:
        handle.remove()
    captured.clear()
    del model, output, image, labels
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()
    return info, data


def isolated(device, source, kind):
    x = source["projection_input"].to(device).detach().requires_grad_(True)
    w = source["projection_weight"].to(device).detach().requires_grad_(True)
    g = source["projection_output_gradient"].to(device)
    if kind.startswith("manual"):
        value = (
            g.reshape(-1, w.shape[0]) @ w
            if kind == "manual2d_input_gradient"
            else g @ w
        ).reshape(x.shape)
        return {"input_gradient": copied(value)}
    original = x.reshape(-1, x.shape[-1]) if kind == "flat2d_explicit_gradient" else x
    value = functional.linear(original, w).reshape(g.shape)
    if kind == "native3d_scalar_dot":
        gradient = torch.autograd.grad((value * g).sum(), (x, w))
    else:
        gradient = torch.autograd.grad(value, (x, w), grad_outputs=g)
    return {
        "output": copied(value),
        "input_gradient": copied(gradient[0]),
        "weight_gradient": copied(gradient[1]),
    }


def environment():
    return {
        "torch": torch.__version__,
        "torch_git": torch.version.git_version,
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "mps_flags": {
            key: os.environ.get(key)
            for key in (
                "PYTORCH_MPS_FAST_MATH",
                "PYTORCH_MPS_PREFER_METAL",
                "PYTORCH_ENABLE_MPS_FALLBACK",
            )
        },
    }


def run(args):
    value = json.loads(args.protocol.read_text())
    validate(BASE)
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen operator source changed: {name}")
    if not torch.backends.mps.is_available():
        raise RuntimeError("ActualMPS required")
    torch.set_num_threads(2)
    archive = np.load(value["inputs"], allow_pickle=False)
    arrays = {key: archive[key] for key in archive.files}
    started = time.perf_counter()
    report = {
        "protocol_sha256": digest(args.protocol),
        "complete": False,
        "environment": environment(),
        "traces": [],
        "boundary_comparisons": {},
        "operators": {},
        "error": None,
    }
    args.artifacts.mkdir(parents=True)
    try:
        traces = []
        for device in value["recipe"]["device_order"]:
            info, data = native_trace(device, arrays)
            path = args.artifacts / (device + "-trace.npz")
            np.savez_compressed(
                path, **{name: tensor.numpy() for name, tensor in data.items()}
            )
            info["arrays_sha256"] = digest(path)
            info["arrays_path"] = str(path)
            report["traces"].append(info)
            traces.append(data)
            print(json.dumps(info), flush=True)
            elapsed_guard(started)
        report["boundary_comparisons"] = {
            name: compare_tensor(traces[0][name], traces[1][name])
            for name in traces[0]
            if name != "labels"
        }
        reference = (
            traces[0]["projection_output_gradient"].double()
            @ traces[0]["projection_weight"].double()
        ).float()
        for kind in value["recipe"]["isolated"]:
            cpu = isolated("cpu", traces[0], kind)
            mps = isolated("mps", traces[0], kind)
            report["operators"][kind] = {
                "cpu_vs_mps": {
                    name: compare_tensor(cpu[name], mps[name]) for name in cpu
                },
                "cpu_vs_fp64_input_reference": compare_tensor(
                    reference, cpu["input_gradient"]
                ),
                "mps_vs_fp64_input_reference": compare_tensor(
                    reference, mps["input_gradient"]
                ),
            }
            elapsed_guard(started)
        report["complete"] = True
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output, report)
        torch.mps.empty_cache()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Use new frozen paths")
    if args.mode == "run" and (args.artifacts is None or args.artifacts.exists()):
        parser.error("Use new numeric artifact directory")
    (freeze if args.mode == "freeze" else run)(args)
