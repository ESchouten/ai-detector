"""Real SDK contract proof with synthetic pixels, not a tracking benchmark."""

import argparse
import copy
import importlib.metadata
import importlib.util
import inspect
import json
import resource
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from detection_cutie import memory_status, open_core


def freeze(args):
    paths = [
        Path(__file__),
        Path(__file__).with_name("cutie_joint_readout.patch"),
        Path(__file__).with_name("benchmark.py"),
        Path(__file__).with_name("detection_cutie.py"),
        args.checkpoint,
    ]
    for root in (args.original, args.candidate):
        paths.extend(sorted((root / "cutie").rglob("*.py")))
        paths.extend(sorted((root / "cutie/config").rglob("*.yaml")))
    value = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "scope": "Synthetic SDK behavior only on the reported actual device: no cattle pixels, labels, model accuracy or live-camera performance claim.",
        "original": str(args.original),
        "candidate": str(args.candidate),
        "checkpoint": str(args.checkpoint),
        "steps": 12,
        "ids": [7, 42, 91],
        "birth_steps": [0, 2, 4],
        "image_shape": [3, 96, 128],
        "allowed_devices": ["cpu", "mps"],
        "max_memory_bytes": 8 * 1024**3,
        "reclaim_bytes": 6 * 1024**3,
        "configuration": {
            "max_internal_size": 480,
            "mem_every": 2,
            "use_long_term": True,
        },
        "requirements": [
            "Exact probability equality at every one-bucket step with one shared network.",
            "Finite three-bucket outputs; stable ObjectManager channels for IDs7/42/91.",
            "Joint fuser sees global other-object masks and runs once per query.",
            "Original fuser/query run three times after three distinct insertion steps.",
            "Identical memory state yields identical per-bucket affinity, visual readout and usage updates.",
            "Positive chunk_size is rejected before reading memory.",
        ],
        "libraries": {
            name: importlib.metadata.version(name)
            for name in ("torch", "torchvision", "hydra-core", "omegaconf", "einops")
        },
        "files": {str(path): digest(path) for path in paths},
    }
    write_json(args.protocol, value)
    print(digest(args.protocol))


def load_candidate(root):
    path = root / "cutie/inference/memory_manager.py"
    spec = importlib.util.spec_from_file_location("joint_readout_candidate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MemoryManager


def recorded_memory(base):
    """Instrument the SDK's affinity boundary without changing its arithmetic."""

    class RecordedMemory(base):
        def __init__(self, cfg, object_manager):
            super().__init__(cfg, object_manager)
            self.record_readout = False
            self.affinities = []
            self.visual_readouts = []

        def _readout(self, affinity, value):
            result = super()._readout(affinity, value)
            if self.record_readout:
                self.affinities.append(affinity.clone())
                self.visual_readouts.append(result.clone())
            return result

    return RecordedMemory


def make_core(network, cfg, memory_type):
    from cutie.inference.inference_core import InferenceCore

    core = InferenceCore(network, cfg)
    # Replace only the freshly constructed, empty store with the reviewed SDK
    # variant. The network, ObjectManager, capture order and core stay identical.
    core.memory = recorded_memory(memory_type)(cfg, core.object_manager)
    return core


def image_and_mask(index, ids):
    import torch

    image = torch.linspace(0, 1, 3 * 96 * 128).reshape(3, 96, 128)
    image = image.roll(index % 7, dims=-1)
    mask = torch.zeros((96, 128), dtype=torch.int64)
    for slot, object_id in enumerate((7, 42, 91)):
        if object_id in ids:
            left = 6 + 40 * slot
            mask[12:84, left : left + 30] = object_id
    return image, mask


@contextmanager
def observe_network(network, expected_last_mask):
    import torch
    import torch.nn.functional as functional

    trace = {"fusion": [], "queries": [], "outputs": []}

    def fusion(_module, values):
        _, _visual, sensory, own, others = values
        expected = functional.interpolate(
            expected_last_mask, size=sensory.shape[-2:], mode="area"
        )
        global_others = (expected.sum(1, keepdim=True) - expected).clamp(0, 1)
        trace["fusion"].append(
            {
                "objects": own.shape[1],
                "global_own_equal": torch.equal(own, expected),
                "global_others_equal": torch.equal(others, global_others),
            }
        )

    def query(_module, values, result):
        trace["queries"].append(values[0].shape[1])
        trace["outputs"].append(result[0].clone())

    handles = [
        network.pixel_fuser.register_forward_pre_hook(fusion),
        network.object_transformer.register_forward_hook(query),
    ]
    try:
        yield trace
    finally:
        for handle in handles:
            handle.remove()


def finite_channels(core, result):
    import torch

    ids = core.object_manager.all_obj_ids
    assert result.shape == (len(ids) + 1, 96, 128)
    assert torch.isfinite(result).all()
    assert torch.allclose(result.sum(0), torch.ones((96, 128)), atol=1e-6)
    for index, object_id in enumerate(ids):
        assert core.object_manager.find_tmp_by_id(object_id) == index + 1
        assert torch.equal(core.last_mask[0, index], result[index + 1])


def guard_memory(recipe, device):
    import torch

    if device == "mps":
        torch.mps.synchronize()
    status = memory_status(device, recipe["reclaim_bytes"])
    # macOS ru_maxrss is bytes (Linux reports KiB).
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    status["peak_rss_bytes"] = peak if sys.platform == "darwin" else peak * 1024
    assert status["mps_driver_bytes"] <= recipe["max_memory_bytes"]
    assert status["peak_rss_bytes"] <= recipe["max_memory_bytes"]
    return status


def single_bucket(network, cfg, original, candidate, recipe, report):
    import torch

    cores = [make_core(network, cfg, kind) for kind in (original, candidate)]
    rows = report["single_bucket_steps"] = []
    for index in range(recipe["steps"]):
        image, mask = image_and_mask(index, recipe["ids"])
        outputs = [
            core.step(image, mask, objects=recipe["ids"], idx_mask=True)
            if index == 0
            else core.step(image)
            for core in cores
        ]
        for core, result in zip(cores, outputs, strict=True):
            finite_channels(core, result)
        equal = torch.equal(*outputs)
        rows.append(
            {
                "step": index,
                "exact_probability_equality": equal,
                "max_absolute_difference": float((outputs[0] - outputs[1]).abs().max()),
                "memory": guard_memory(recipe, report["requested_device"]),
            }
        )
        assert equal, f"Single-bucket probabilities changed at step {index}"


def multiple_buckets(network, cfg, original, candidate, recipe, report):
    cores = [make_core(network, cfg, kind) for kind in (original, candidate)]
    rows = report["multiple_bucket_steps"] = []
    schedule = dict(zip(recipe["birth_steps"], recipe["ids"], strict=True))
    for index in range(recipe["steps"]):
        incoming = [schedule[index]] if index in schedule else []
        image, mask = image_and_mask(index, incoming)
        row = {"step": index, "incoming": incoming}
        for name, core in zip(("original", "joint"), cores, strict=True):
            expected = core.last_mask
            if expected is None:
                result = core.step(image, mask, objects=incoming, idx_mask=True)
                trace = {"fusion": [], "queries": []}
            else:
                with observe_network(network, expected) as trace:
                    result = (
                        core.step(image, mask, objects=incoming, idx_mask=True)
                        if incoming
                        else core.step(image)
                    )
                del trace["outputs"]
            finite_channels(core, result)
            row[name] = trace
            if name == "joint":
                assert all(
                    item["global_own_equal"] and item["global_others_equal"]
                    for item in trace["fusion"]
                )
            if index > max(recipe["birth_steps"]):
                expected_count = 3 if name == "original" else 1
                assert len(trace["fusion"]) == len(trace["queries"]) == expected_count
        row["memory"] = guard_memory(recipe, report["requested_device"])
        rows.append(row)
    assert cores[0].object_manager.all_obj_ids == recipe["ids"]
    buckets = cores[0].memory.work_mem.buckets
    assert list(buckets.values()) == [[7], [42], [91]]
    lengths = [cores[0].memory.work_mem.size(bucket) for bucket in buckets]
    report["bucket_token_lengths"] = lengths
    assert len(set(lengths)) == 3, "Expected different insertion-time histories"
    return cores[0]


def usage_equal(left, right):
    import torch

    for name in ("work_mem", "long_mem"):
        a, b = getattr(left, name), getattr(right, name)
        for counter in ("use_cnt", "life_cnt"):
            aa, bb = getattr(a, counter), getattr(b, counter)
            assert aa.keys() == bb.keys()
            assert all(torch.equal(aa[key], bb[key]) for key in aa)


def identical_state(core, original, candidate, report):
    import torch

    image, _ = image_and_mask(12, [])
    features, pixel = core.network.encode_image(image.unsqueeze(0))
    key, _, selection = core.network.transform_key(features[0])
    copies = [copy.deepcopy(core.memory), copy.deepcopy(core.memory)]
    traces = []
    for memory, kind in zip(copies, (original, candidate), strict=True):
        memory.record_readout = True
        with observe_network(core.network, core.last_mask) as trace:
            output = kind.read(
                memory, pixel, key, selection, core.last_mask, core.network
            )
        ids = core.object_manager.all_obj_ids
        assert list(output) == ids
        if kind is candidate:
            assert len(trace["outputs"]) == 1
            assert all(
                torch.equal(output[object_id], trace["outputs"][0][:, index])
                for index, object_id in enumerate(ids)
            )
        else:
            assert all(
                torch.equal(output[object_id], trace["outputs"][index][:, 0])
                for index, object_id in enumerate(ids)
            )
        assert all(torch.isfinite(value).all() for value in output.values())
        traces.append(trace)
    for attribute in ("affinities", "visual_readouts"):
        a, b = (getattr(memory, attribute) for memory in copies)
        assert len(a) == len(b) == 3
        assert all(torch.equal(x, y) for x, y in zip(a, b, strict=True))
    usage_equal(*copies)
    report["identical_state"] = {
        "affinities_exact": True,
        "visual_readouts_exact": True,
        "usage_updates_exact": True,
        "stable_id_output_mapping_exact": True,
        "original_fuser_calls": len(traces[0]["fusion"]),
        "joint_fuser_calls": len(traces[1]["fusion"]),
    }
    copies[1].chunk_size = 1
    try:
        candidate.read(copies[1], pixel, key, selection, core.last_mask, core.network)
    except ValueError as error:
        report["positive_chunk_rejected"] = str(error)
    else:
        raise AssertionError("Positive chunk size was accepted")


def run(args):
    recipe = json.loads(args.protocol.read_text())
    for filename, expected in recipe["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Frozen input changed: {filename}")
    for name, expected in recipe["libraries"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError(f"Frozen library changed: {name}")
    if args.device not in recipe["allowed_devices"]:
        raise ValueError("Device is outside the frozen proof recipe")

    def deny_network(event, _arguments):
        if event in {"urllib.Request", "socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("Network disabled in the synthetic SDK proof")

    sys.addaudithook(deny_network)
    import torch
    from cutie.inference.memory_manager import MemoryManager

    torch.set_num_threads(2)
    torch.manual_seed(0)
    assert Path(inspect.getfile(MemoryManager)).is_relative_to(recipe["original"])
    candidate = load_candidate(Path(recipe["candidate"]))
    report = {
        "protocol_sha256": digest(args.protocol),
        "passed": False,
        "requested_device": args.device,
    }
    started = time.perf_counter()
    try:
        core, config = open_core(
            SimpleNamespace(
                upstream=Path(recipe["original"]),
                model=Path(recipe["checkpoint"]),
                device=args.device,
            ),
            recipe["configuration"],
        )
        network, cfg = core.network, core.cfg
        parameter = next(network.parameters())
        assert parameter.device.type == args.device and parameter.dtype == torch.float32
        assert cfg.chunk_size == -1 and not cfg.save_aux
        report.update(
            actual_device=str(parameter.device),
            actual_dtype=str(parameter.dtype),
            torch=torch.__version__,
            config=config,
        )
        with torch.inference_mode(), torch.device(args.device):
            single_bucket(network, cfg, MemoryManager, candidate, recipe, report)
            state = multiple_buckets(
                network, cfg, MemoryManager, candidate, recipe, report
            )
            identical_state(state, MemoryManager, candidate, report)
            report["final_memory"] = guard_memory(recipe, args.device)
        report["passed"] = True
    except Exception:
        # This executable is the experiment boundary: retain failures and rethrow.
        report["failure"] = traceback.format_exc()
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output, report)
    print(json.dumps({key: report[key] for key in ("passed", "elapsed_seconds")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    args = parser.parse_args()
    destination = args.protocol if args.mode == "freeze" else args.output
    if destination is None or destination.exists():
        parser.error("Choose a new output path; prior protocols/results are immutable")
    freeze(args) if args.mode == "freeze" else run(args)
