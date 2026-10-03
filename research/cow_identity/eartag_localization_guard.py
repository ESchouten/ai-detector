"""External execution guard for the unchanged, frozen 11-image evaluator."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from eartag_localization_evaluate import inference
from eartag_localization_training import RESULTS, digest, write

PROTOCOL = Path(__file__).with_name("eartag_localization_evaluate_protocol.json")
EXPECTED = "5fbf1ba423e128d035d96b72a12c3f4d87bf544a60ccac1b2b4e891afc72deac"
RAW = RESULTS / "localization-raw.json"
REPORT = RESULTS / "localization-execution.json"
LIMIT = 8 * 1024**3


def main():
    import psutil
    import torch

    if digest(PROTOCOL) != EXPECTED or RAW.exists() or REPORT.exists():
        raise ValueError("Keep the frozen protocol and any prior execution unchanged")
    started = time.monotonic()
    stop = threading.Event()
    peaks = {"rss_bytes": 0, "mps_driver_bytes": 0}
    metadata = {
        "protocol_sha256": EXPECTED,
        "guard_sha256": digest(__file__),
        "limits": {"seconds": 180, "rss_bytes": LIMIT, "mps_driver_bytes": LIMIT},
        "scope": "Execution watchdog only; original evaluator/model/settings unchanged.",
    }

    def report(status, **extra):
        write(
            REPORT,
            {
                **metadata,
                "status": status,
                "seconds": time.monotonic() - started,
                "peaks": dict(peaks),
                **extra,
            },
        )

    def sample():
        peaks["rss_bytes"] = max(peaks["rss_bytes"], psutil.Process().memory_info().rss)
        peaks["mps_driver_bytes"] = max(
            peaks["mps_driver_bytes"], torch.mps.driver_allocated_memory()
        )

    def watch():
        while not stop.wait(0.05):
            try:
                sample()
                if max(peaks.values()) > LIMIT or time.monotonic() - started >= 180:
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
        sample()
    except BaseException as error:
        stop.set()
        thread.join()
        report("FAILED_FROZEN_INFERENCE", error=repr(error))
        raise
    stop.set()
    thread.join()
    report("COMPLETE_FIXED_INFERENCE", raw_sha256=digest(RAW))


if __name__ == "__main__":
    main()
