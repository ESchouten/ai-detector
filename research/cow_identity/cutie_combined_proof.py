"""Offline CPU proof of the combined inference, memory and retirement SDK wheel."""

import argparse
import email
import importlib.metadata
import importlib.resources
import importlib.util
import inspect
import json
import os
import sys
import time
import traceback
import zipfile
from pathlib import Path

from benchmark import digest, write_json
from cutie_joint_readout_proof import finite_channels, image_and_mask, observe_network
from cutie_retirement_proof import exercise

CHANGED = {
    "cutie/model/big_modules.py",
    "cutie/inference/inference_core.py",
    "cutie/inference/memory_manager.py",
    "cutie/inference/kv_memory_store.py",
}


def package_contract(recipe):
    upstream = Path(recipe["upstream"])
    installed = Path(recipe["installed"])
    with zipfile.ZipFile(recipe["wheel"]) as wheel:
        names = wheel.namelist()
        metadata = email.message_from_bytes(
            wheel.read(next(p for p in names if p.endswith(".dist-info/METADATA")))
        )
        assert metadata["Version"] == "1.0.0+aidetector.2"
        assert set(metadata.get_all("Requires-Dist")) == {
            "torch>=2.0",
            "numpy>=1.21",
            "hydra-core>=1.3.2",
        }
        package_files = [p for p in names if p.startswith("cutie/")]
        changed = {
            p for p in package_files if wheel.read(p) != (upstream / p).read_bytes()
        }
        assert changed == CHANGED
        assert all(wheel.read(p) == (installed / p).read_bytes() for p in package_files)
        configs = {p for p in names if p.endswith(".yaml")}
        assert configs == {
            str(p.relative_to(upstream))
            for p in (upstream / "cutie/config").rglob("*.yaml")
        }
        license_name = next(p for p in names if p.endswith("/licenses/LICENSE"))
        assert wheel.read(license_name) == (upstream / "LICENSE").read_bytes()
    return {"changed_files": sorted(changed), "yaml_resources": len(configs)}


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compare_no_retirement(network, config, joint, report):
    """Actual probabilities remain exact with births and memory consolidation."""
    import torch
    from cutie.inference.inference_core import InferenceCore

    previous_memory = module_at(
        "previous_joint_memory", joint / "cutie/inference/memory_manager.py"
    )
    previous_core = module_at(
        "previous_joint_core", joint / "cutie/inference/inference_core.py"
    )
    previous_core.MemoryManager = previous_memory.MemoryManager
    cores = (
        previous_core.InferenceCore(network, config),
        InferenceCore(network, config),
    )
    schedule = {0: 7, 2: 42, 4: 91}
    rows = report["parity_steps"] = []
    for index in range(16):
        incoming = [schedule[index]] if index in schedule else []
        image, mask = image_and_mask(index, incoming)
        outputs = [
            core.step(image, mask, objects=incoming, idx_mask=True)
            if incoming
            else core.step(image)
            for core in cores
        ]
        for core, result in zip(cores, outputs, strict=True):
            finite_channels(core, result)
        equal = torch.equal(*outputs)
        rows.append({"step": index, "exact_probabilities": equal})
        assert equal, f"Combined wheel changed existing joint outputs at step{index}"
    assert all(core.memory.long_mem.engaged() for core in cores)
    report["long_term_consolidation_exercised"] = True
    return cores[1]


def retire_and_reinsert(core, report):
    """Retire a middle insertion-time bucket, then query all surviving objects."""
    import torch

    survivor = core.last_mask[:, [0, 2]].clone()
    core.delete_objects([42])
    assert core.object_manager.all_obj_ids == [7, 91]
    assert torch.equal(core.last_mask, survivor)
    assert set(core.memory.obj_v) == {7, 91}
    for store in (core.memory.work_mem, core.memory.long_mem):
        assert 42 not in store.v
        assert all(42 not in values for values in store.buckets.values())
    rows = report["post_retirement_steps"] = []
    for index in range(16, 24):
        image, _ = image_and_mask(index, [])
        with observe_network(core.network, core.last_mask) as trace:
            if index == 18:
                mask = torch.zeros((96, 128), dtype=torch.int64)
                mask[12:84, 46:76] = 105
                output = core.step(image, mask, objects=[105], idx_mask=True)
            else:
                output = core.step(image)
        finite_channels(core, output)
        assert len(trace["fusion"]) == len(trace["queries"]) == 1
        assert all(
            item["global_own_equal"] and item["global_others_equal"]
            for item in trace["fusion"]
        )
        assert 42 not in core.memory.obj_v
        rows.append(
            {
                "step": index,
                "ids": list(core.object_manager.all_obj_ids),
                "joint_fusion": True,
            }
        )
    assert core.object_manager.all_obj_ids == [7, 91, 105]
    assert core.object_manager.find_tmp_by_id(105) == 3
    core.delete_objects([7, 91, 105])
    assert core.last_mask.shape[1] == 0
    assert not core.memory.obj_v and not core.memory.sensory
    assert not core.memory.work_mem.engaged() and not core.memory.long_mem.engaged()
    report["all_active_memory_removed"] = True
    image, _ = image_and_mask(24, [])
    with observe_network(core.network, core.last_mask) as trace:
        empty = core.step(image)
    assert not trace["fusion"] and not trace["queries"]
    assert empty.shape == (1, 96, 128) and torch.count_nonzero(empty) == 0
    mask = torch.zeros((96, 128), dtype=torch.int64)
    mask[12:84, 46:76] = 211
    core.step(image, mask, objects=[211], idx_mask=True)
    final = core.step(image)
    finite_channels(core, final)
    assert core.object_manager.all_obj_ids == [211]
    assert set(core.memory.obj_v) == {211}
    report["empty_step_bypasses_readout_then_new_id_initializes"] = True


def load_network(recipe):
    import torch
    from cutie.inference.inference_core import InferenceCore
    from cutie.model.cutie import CUTIE
    from hydra import compose, initialize_config_dir
    from omegaconf import OmegaConf

    assert Path(inspect.getfile(CUTIE)).is_relative_to(recipe["installed"])
    assert Path(inspect.getfile(InferenceCore)).is_relative_to(recipe["installed"])
    config_path = str(importlib.resources.files("cutie") / "config")
    with initialize_config_dir(version_base="1.3.2", config_dir=config_path):
        config = compose(config_name="eval_config")
    for key, value in recipe["configuration"].items():
        OmegaConf.update(config, key, value, force_add=True)
    model = CUTIE(config).eval()
    checkpoint = torch.load(recipe["checkpoint"], map_location="cpu", weights_only=True)
    result = model.load_state_dict(checkpoint, strict=True)
    assert not result.missing_keys and not result.unexpected_keys
    state = model.state_dict()
    assert set(state) == set(checkpoint)
    assert all(torch.equal(state[key], checkpoint[key]) for key in state)
    assert all(
        p.device.type == "cpu" and p.dtype == torch.float32 for p in model.parameters()
    )
    return model, config, len(state)


def run(args):
    if args.output.exists():
        raise FileExistsError("Preserve every proof result")
    recipe = json.loads(args.protocol.read_text())
    for path, expected in recipe["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen combined proof input changed: {path}")
    assert {
        name: importlib.metadata.version(name) for name in recipe["libraries"]
    } == recipe["libraries"]
    report = {"protocol_sha256": digest(args.protocol), "passed": False}
    report["package"] = package_contract(recipe)
    cache = args.output.parent / "combined-proof-empty-torch-cache"
    cache.mkdir(exist_ok=False)
    os.environ["TORCH_HOME"] = str(cache)
    attempts = []

    def deny_network(event, _arguments):
        if event in {"urllib.Request", "socket.connect", "socket.getaddrinfo"}:
            attempts.append(event)
            raise RuntimeError("Network disabled during combined wheel proof")

    sys.addaudithook(deny_network)
    import torch
    from cutie.inference.inference_core import InferenceCore

    torch.set_num_threads(2)
    torch.manual_seed(0)
    started = time.perf_counter()
    try:
        model, config, tensor_count = load_network(recipe)
        report["strict_equal_checkpoint_tensors"] = tensor_count
        with torch.inference_mode():
            core = compare_no_retirement(model, config, Path(recipe["joint"]), report)
            retire_and_reinsert(core, report)
            checks = {}
            exercise(InferenceCore(model, config), checks)
            assert len(checks) == 8 and all(checks.values())
            report["previous_retirement_checks"] = checks
        assert not attempts
        report["passed"] = True
    except Exception:
        report["failure"] = traceback.format_exc()
        raise
    finally:
        report.update(
            network_attempts=attempts,
            elapsed_seconds=time.perf_counter() - started,
            scope="Actual CPU FP32 inference on synthetic96x128pixels only. No cattle accuracy, MPS, application dependency change or live-camera throughput claim.",
        )
        write_json(args.output, report)
    print(json.dumps({key: report[key] for key in ("passed", "elapsed_seconds")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
