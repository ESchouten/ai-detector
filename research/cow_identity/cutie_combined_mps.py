"""Repeat the frozen installed-wheel CPU contracts on actual MPS, without cattle."""

import argparse
import importlib.metadata
import json
import os
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from benchmark import digest, write_json
from cutie_combined_proof import (
    compare_no_retirement,
    load_network,
    package_contract,
    retire_and_reinsert,
)
from cutie_joint_readout_proof import guard_memory
from cutie_retirement_proof import exercise

ROOT = Path(__file__).parent
CPU_PROTOCOL = ROOT / "cutie_combined_protocol.json"
CPU_RESULT = ROOT / "results/2026-10-03/detection/cutie-combined-cpu.json"
LIBRARIES = (
    "cutie",
    "torch",
    "torchvision",
    "numpy",
    "hydra-core",
    "omegaconf",
    "antlr4-python3-runtime",
)


def versions():
    return {name: importlib.metadata.version(name) for name in LIBRARIES}


def verify_files(files):
    for filename, expected in files.items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Frozen combined MPS input changed: {filename}")


def freeze(path):
    recipe = json.loads(CPU_PROTOCOL.read_text())
    verify_files(recipe["files"])
    result = json.loads(CPU_RESULT.read_text())
    if not result["passed"] or result["protocol_sha256"] != digest(CPU_PROTOCOL):
        raise ValueError("The exact CPU prerequisite must have passed")
    recipe["files"].update(
        {str(p): digest(p) for p in (Path(__file__), CPU_PROTOCOL, CPU_RESULT)}
    )
    recipe.update(
        frozen_at_utc=datetime.now(UTC).isoformat(),
        status="FROZEN_PENDING_EXPLICIT_GPU_RELEASE",
        device="mps",
        libraries=versions(),
        max_memory_bytes=8 * 1024**3,
        reclaim_bytes=6 * 1024**3,
        scope=(
            "One CPU strict load followed by actual FP32 MPS synthetic96x128 "
            "inference. Reuse unchanged combined proof:16 exact probability "
            "steps, three insertion buckets and forced consolidation, middle "
            "retirement/new105/all retirement/empty bypass/new211, plus eight "
            "earlier lifecycle checks. No cattle, accuracy, live throughput, "
            "long-running memory bound or CPU-versus-MPS numerical parity claim."
        ),
        memory_observation=(
            "Synchronized stage-boundary driver samples before/after optional "
            "6GiB cache reclamation;8GiB post-reclamation driver and process "
            "peak RSS caps. Stage samples are not the peak Metal allocation."
        ),
    )
    write_json(path, recipe)
    print(digest(path))


def verify(path):
    recipe = json.loads(path.read_text())
    verify_files(recipe["files"])
    if recipe["libraries"] != versions() or recipe["device"] != "mps":
        raise ValueError("Frozen installed SDK, libraries or device changed")
    return recipe


def mark_stage(recipe, report, stage, started):
    status = guard_memory(recipe, "mps")
    report["stages"].append(
        {"stage": stage, "elapsed_seconds": time.perf_counter() - started, **status}
    )


def exercise_mps(recipe, report):
    import torch
    from cutie.inference.inference_core import InferenceCore

    torch.set_num_threads(2)
    torch.manual_seed(0)
    model, config, tensors = load_network(recipe)
    report["strict_equal_checkpoint_tensors"] = tensors
    model.to("mps")
    parameter = next(model.parameters())
    assert all(
        p.device.type == "mps" and p.dtype == torch.float32 for p in model.parameters()
    )
    report.update(
        actual_device=str(parameter.device), actual_dtype=str(parameter.dtype)
    )
    started = time.perf_counter()
    mark_stage(recipe, report, "loaded_on_mps", started)
    with torch.inference_mode(), torch.device("mps"):
        core = compare_no_retirement(model, config, Path(recipe["joint"]), report)
        assert core.last_mask.device.type == "mps"
        mark_stage(recipe, report, "exact_parity_and_consolidation", started)
        retire_and_reinsert(core, report)
        assert core.last_mask.device.type == "mps"
        mark_stage(recipe, report, "retired_and_reinserted", started)
        del core
        checks = {}
        exercise(InferenceCore(model, config), checks)
        assert len(checks) == 8 and all(checks.values())
        report["previous_retirement_checks"] = checks
        mark_stage(recipe, report, "previous_lifecycle_checks", started)


def run(protocol_path, output):
    recipe = verify(protocol_path)
    report = {
        "protocol_sha256": digest(protocol_path),
        "passed": False,
        "scope": recipe["scope"],
        "memory_observation": recipe["memory_observation"],
        "libraries": recipe["libraries"],
        "package": package_contract(recipe),
        "stages": [],
    }
    cache = output.parent / "combined-mps-empty-torch-cache"
    cache.mkdir(exist_ok=False)
    os.environ["TORCH_HOME"] = str(cache)
    attempts = []

    def deny_network(event, _arguments):
        if event in {"urllib.Request", "socket.connect", "socket.getaddrinfo"}:
            attempts.append(event)
            raise RuntimeError("Network disabled during combined MPS proof")

    sys.addaudithook(deny_network)
    started = time.perf_counter()
    try:
        import torch

        if not torch.backends.mps.is_available():
            raise RuntimeError("Actual MPS is required; no CPU fallback")
        exercise_mps(recipe, report)
        assert not attempts
        report["passed"] = True
    except Exception:
        report["failure"] = traceback.format_exc()
        raise
    finally:
        report.update(
            network_attempts=attempts,
            elapsed_seconds=time.perf_counter() - started,
        )
        write_json(output, report)
    print(json.dumps({key: report[key] for key in ("passed", "elapsed_seconds")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "verify", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            parser.error("Preserve the original freeze")
        freeze(args.protocol)
    elif args.mode == "verify":
        value = verify(args.protocol)
        print(json.dumps({"verified_bindings": len(value["files"])}))
    else:
        if args.output is None or args.output.exists():
            parser.error("Preserve every run in a fresh output")
        run(args.protocol, args.output)
