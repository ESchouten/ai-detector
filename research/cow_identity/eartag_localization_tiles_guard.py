"""Bounded execution wrapper; immutable scientific settings live in protocol."""

import os
import threading
import time
from pathlib import Path

from eartag_localization_tiles import inference
from eartag_localization_training import RESULTS, checked, digest, write

PROTOCOL = Path(__file__).with_name("eartag_localization_tiles_protocol.json")
RAW = RESULTS / "localization-tiles-raw.json"
REPORT = RESULTS / "localization-tiles-execution.json"


def main():
    import psutil
    import torch

    document = checked(PROTOCOL)
    if RAW.exists() or REPORT.exists():
        raise ValueError("Preserve prior execution")
    started, stopped = time.monotonic(), threading.Event()
    peaks = {"rss_bytes": 0, "mps_driver_bytes": 0}

    def report(status, **extra):
        write(
            REPORT,
            {
                "status": status,
                "protocol_sha256": digest(PROTOCOL),
                "seconds": time.monotonic() - started,
                "peaks": dict(peaks),
                "limits": document["limits"],
                **extra,
            },
        )

    def sample():
        peaks["rss_bytes"] = max(peaks["rss_bytes"], psutil.Process().memory_info().rss)
        peaks["mps_driver_bytes"] = max(
            peaks["mps_driver_bytes"], torch.mps.driver_allocated_memory()
        )
        return time.monotonic() - started >= document["limits"]["seconds"] or any(
            v > document["limits"][k] for k, v in peaks.items()
        )

    def watch():
        while not stopped.wait(0.05):
            try:
                if sample():
                    report("STOPPED_RESOURCE_OR_TIME_LIMIT")
                    os._exit(77)
            except Exception as error:
                report("FAILED_RESOURCE_MONITOR", error=repr(error))
                os._exit(78)

    report("STARTED_BEFORE_INFERENCE")
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        inference(PROTOCOL, RAW)
        if sample():
            raise RuntimeError("Resource cap exceeded on final sample")
    except BaseException as error:
        stopped.set()
        thread.join()
        report("FAILED_FROZEN_INFERENCE", error=repr(error))
        raise
    stopped.set()
    thread.join()
    report("COMPLETE_FIXED_TILE_INFERENCE", raw_sha256=digest(RAW))


if __name__ == "__main__":
    main()
