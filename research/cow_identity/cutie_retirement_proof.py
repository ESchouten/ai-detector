"""CPU SDK lifecycle probe, independent of animal labels or accuracy scores."""

import argparse
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from detection_cutie import open_core


def exercise(core, checks):
    import torch
    import torch.nn.functional as functional

    image = torch.linspace(0, 1, 3 * 96 * 128).reshape(3, 96, 128)
    mask = torch.zeros((96, 128), dtype=torch.int64)
    mask[8:88, 8:56], mask[8:88, 72:120] = 7, 42
    core.step(image, mask, objects=[7, 42], idx_mask=True)
    survivor = core.last_mask[:, 1:2].clone()
    core.delete_objects([7])
    checks["survivor_channel_compacted"] = torch.equal(core.last_mask, survivor)
    checks["retired_summary_removed"] = set(core.memory.obj_v) == {42}
    assert core.object_manager.find_tmp_by_id(42) == 1

    def observe_readout(_module, values):
        expected = functional.interpolate(
            survivor, size=values[2].shape[-2:], mode="area"
        )
        checks["next_step_reads_survivor_mask"] = torch.equal(values[3], expected)

    hook = core.network.pixel_fuser.register_forward_pre_hook(observe_readout)
    prediction = core.step(image)
    hook.remove()
    assert prediction.shape == (2, 96, 128)
    core.delete_objects([42])
    checks["all_previous_channels_removed"] = core.last_mask.shape[1] == 0
    checks["all_summaries_removed"] = not core.memory.obj_v
    checks["all_bucket_offsets_removed"] = not core.memory.work_mem.perm_end_pt
    assert not core.object_manager.all_obj_ids
    assert not core.memory.work_mem.engaged()

    mask[mask > 0] = 91
    core.step(image, mask, objects=[91], idx_mask=True)
    assert core.object_manager.all_obj_ids == [91]
    assert core.object_manager.find_tmp_by_id(91) == 1
    checks["new_object_has_only_its_summary"] = set(core.memory.obj_v) == {91}
    checks["new_object_has_only_its_bucket_offset"] = set(
        core.memory.work_mem.perm_end_pt
    ) == set(core.memory.work_mem.buckets)
    final = core.step(image)
    assert final.shape == (2, 96, 128)
    assert core.last_mask.shape[1] == 1


def run(args):
    def deny_network(event, _arguments):
        if event in {"urllib.Request", "socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("Network disabled in the SDK lifecycle proof")

    sys.addaudithook(deny_network)
    import torch

    torch.set_num_threads(2)
    core, _ = open_core(
        SimpleNamespace(upstream=args.upstream, model=args.checkpoint, device="cpu"),
        {"max_internal_size": 480, "mem_every": 5, "use_long_term": True},
    )
    assert Path(inspect.getfile(type(core))).is_relative_to(args.upstream)
    checks = {}
    failure = None
    try:
        with torch.inference_mode():
            exercise(core, checks)
    except (KeyError, RuntimeError) as error:
        failure = f"{type(error).__name__}: {error}"

    paths = [
        args.upstream / "cutie/inference" / filename
        for filename in (
            "inference_core.py",
            "memory_manager.py",
            "kv_memory_store.py",
            "object_manager.py",
        )
    ]
    report = {
        "scope": "Real CPU inference with synthetic pixels; tests SDK state ownership, not animal tracking, naming or a retirement policy.",
        "expected": args.expected,
        "checks": checks,
        "failure": failure,
        "checkpoint_sha256": digest(args.checkpoint),
        "source_sha256": {str(path): digest(path) for path in paths},
        "probe_sha256": digest(Path(__file__)),
        "torch": torch.__version__,
        "device": "cpu",
    }
    write_json(args.output, report)
    print(report)
    assert (failure is None and len(checks) == 8 and all(checks.values())) == (
        args.expected == "fixed"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "checkpoint", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--expected", choices=("original", "fixed"), required=True)
    run(parser.parse_args())
