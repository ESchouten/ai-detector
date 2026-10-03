"""Hardware lifecycle control; synthetic inputs do not measure cattle accuracy."""

import argparse
import inspect
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from cutie_retirement_proof import exercise
from detection_cutie import memory_status, open_core


def verify_cycle(core):
    import torch

    checks = {}
    exercise(core, checks)
    torch.mps.synchronize()
    if len(checks) != 8 or not all(checks.values()):
        raise AssertionError(f"Failed state ownership: {checks}")
    return checks


def run(args):
    protocol = json.loads(args.protocol.read_text())
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Frozen input changed: {filename}")

    def deny_network(event, _arguments):
        if event in {"urllib.Request", "socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("Network disabled in the lifecycle control")

    sys.addaudithook(deny_network)
    import torch
    from cutie.inference.inference_core import InferenceCore

    if not torch.backends.mps.is_available():
        raise RuntimeError("This control requires MPS")
    torch.set_num_threads(2)
    core, config = open_core(
        SimpleNamespace(
            upstream=Path(protocol["upstream"]),
            model=Path(protocol["checkpoint"]),
            device="mps",
        ),
        protocol["configuration"],
    )
    if not Path(inspect.getfile(type(core))).is_relative_to(protocol["upstream"]):
        raise ValueError("Wrong SDK source imported")
    network, cfg = core.network, core.cfg
    rows = []
    report = {
        "scope": protocol["scope"],
        "protocol_sha256": digest(args.protocol),
        "torch": torch.__version__,
        "device": "mps",
        "configuration": config,
        "cycles": rows,
        "passed": False,
        "failure": None,
    }
    try:
        with torch.inference_mode(), torch.device("mps"):
            for cycle in range(protocol["cycles"]):
                started = time.perf_counter()
                checks = verify_cycle(core)
                historical_ids = len(core.object_manager.all_historical_object_ids)
                # An empty-camera epoch releases the whole core, not only tensors.
                # Keep shared weights; never reuse a retired biological binding.
                del core
                torch.mps.empty_cache()
                core = InferenceCore(network, cfg)
                status = memory_status("mps", protocol["reclaim_bytes"])
                rows.append(
                    {
                        "cycle": cycle,
                        "seconds": time.perf_counter() - started,
                        "checks": checks,
                        "historical_ids_before_core_disposal": historical_ids,
                        "new_core_empty": not core.object_manager.all_obj_ids
                        and not core.object_manager.all_historical_object_ids,
                        **status,
                    }
                )
                if status["mps_driver_bytes"] > protocol["max_driver_bytes"]:
                    raise RuntimeError("Frozen MPS memory budget exceeded")
        report["passed"] = len(rows) == protocol["cycles"] and all(
            row["new_core_empty"] for row in rows
        )
    except (AssertionError, KeyError, RuntimeError) as error:
        report["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
