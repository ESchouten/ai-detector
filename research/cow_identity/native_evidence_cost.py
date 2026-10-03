"""Bounded CPU cost of exact native evidence through the real collector/store."""

import argparse
import hashlib
import importlib.metadata
import os
import platform
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json

from aidetector.adapters.identity_profile_collector import IdentityProfileCollector
from aidetector.adapters.identity_profiles import IdentityProfileStore
from aidetector.adapters.inference.continuous_identity import TrackEvidence
from aidetector.adapters.media.images import shrink_image
from aidetector.domain.live_identity import LiveTarget
from aidetector.domain.models import BoundingBox, CaptureStamp

AT = datetime(2026, 10, 3, tzinfo=UTC)
SOURCE = "synthetic-camera"
SHAPES = ((720, 1280, 3), (1440, 2560, 3), (2160, 3840, 3))


def pixels_sha(image):
    value = hashlib.sha256(str((image.shape, image.dtype)).encode())
    value.update(image.tobytes())
    return value.hexdigest()


def collect_period(collector, clock, analysis, native, period):
    timed = None
    height, width = analysis.shape[:2]
    for second in range(period * 10, period * 10 + 10):
        clock[0] = second + 0.1
        items = [
            TrackEvidence(
                SOURCE,
                CaptureStamp("synthetic-epoch", second * 30, float(second)),
                LiveTarget(f"instance-{index}", index + 1, 0),
                BoundingBox(0, 0, width - 1, height - 1, "cow", track_id=index + 1),
                0.9,
                analysis,
                second,
                AT + timedelta(seconds=second),
                native,
            )
            for index in range(8)
        ]
        calls = []
        started = time.perf_counter()
        for item in items:
            tick = time.perf_counter()
            collector(item)
            calls.append(time.perf_counter() - tick)
        elapsed = time.perf_counter() - started
        if second % 10 == 2:
            timed = {"second": second, "seconds": elapsed, "call_seconds": calls}
    assert timed is not None
    return timed


def verify(directory, shape, expected):
    store = IdentityProfileStore(directory, "inspection-only")
    try:
        facts, usage = store.snapshot(), store.usage()
        assert (len(facts), usage["images"], usage["profiles"]) == (48, 6, 8)
        encoded_sizes = []
        for second, expected_pixels in expected.items():
            group = [row for row in facts if row["analysis_index"] == second]
            assert len(group) == 8 and len({r["encoded_sha256"] for r in group}) == 1
            assert len({r["instance_id"] for r in group}) == 8
            for row in group:
                assert row["epoch"] == "synthetic-epoch"
                assert row["capture_sequence"] == second * 30
                assert row["image_shape"] == list(shape)
                assert row["analysis_shape"] == [720, 1280, 3]
                assert row["box"] == [0, 0, shape[1] - 1, shape[0] - 1]
                assert row["image_resolution"] == "source"
                assert row["image_encoding"] == "source-resolution-jpeg-quality95"
                assert row["original_pixels_sha256"] == expected_pixels
            image = store.image(group[0]["id"])
            assert image is not None
            assert (
                cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR).shape
                == shape
            )
            encoded_sizes.append(len(image))
        assert len({r["encoded_sha256"] for r in facts}) == 6
        assert len(expected) == 6 and len(set(expected.values())) == 6
        raw_bytes = int(np.prod(shape))
        assert raw_bytes <= 32 * 1024**2
        assert raw_bytes + max(encoded_sizes) <= 48 * 1024**2
        assert usage["database_bytes"] <= 256 * 1024**2
        return {**usage, "jpeg_bytes": encoded_sizes, "native_bytes": raw_bytes}
    finally:
        store.close()


def measure(shape):
    rng = np.random.default_rng(17)
    clock = [0.0]
    timed, expected, statuses = [], {}, []
    with tempfile.TemporaryDirectory(prefix="cow-native-cost-") as temporary:
        directory = Path(temporary)
        collector = IdentityProfileCollector(
            directory,
            "synthetic-run",
            SOURCE,
            clock=lambda: clock[0],
            report_status=statuses.append,
        )
        collector.source_changed("synthetic-epoch")
        try:
            for period in range(6):
                native = rng.integers(0, 256, shape, dtype=np.uint8)
                native.setflags(write=False)
                analysis = shrink_image(native, 1280)
                analysis.setflags(write=False)
                timed.append(collect_period(collector, clock, analysis, native, period))
                expected[period * 10 + 2] = pixels_sha(native)
        finally:
            collector.close()
        assert statuses == [], "Collection errors must not be hidden by timing"
        storage = verify(directory, shape, expected)
    durations = [r["seconds"] for r in timed]
    calls = [value for row in timed for value in row["call_seconds"]]
    return {
        "native_shape": list(shape),
        "analysis_shape": [720, 1280, 3],
        "collector_callbacks": 480,
        "saving_callbacks": len(calls),
        "saving_frames": len(timed),
        "eight_instance_frame_median_seconds": statistics.median(durations),
        "eight_instance_frame_maximum_seconds": max(durations),
        "saving_callback_median_seconds": statistics.median(calls),
        "saving_callback_maximum_seconds": max(calls),
        "saving_frames_detail": timed,
        "storage": storage,
        "verified": True,
    }


def main(output):
    if output.exists():
        raise ValueError("Keep previous measurements")
    cv2.setNumThreads(2)
    started = time.perf_counter()
    root = Path("detector/src/aidetector")
    sources = [Path(__file__), *sorted(root.rglob("*.py"))]
    report = {
        "files": {str(p): digest(p) for p in sources},
        "scope": "Synthetic CPU storage cost only. Same readonly native image shared by8 instances,6 independent noise images per resolution; real collector3-consecutive qualification and10-second cadence. Controlled clock is NOT a real-time deadline or endurance proof.",
        "timing": "Time the8 actual collector calls for each saving frame, including first lazy database initialization, pixel hash, quality95 JPEG, quota checks and SQLite writes. Exclude random generation, resizing, constructing TrackEvidence, verification and teardown. The previous native JPEG cache may be replaced inside the timed calls.",
        "limits": {"seconds": 120, "opencv_threads": 2},
        "libraries": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "opencv-python")
        },
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "thread_environment": {
            name: os.environ.get(name)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "opencv_threads": cv2.getNumThreads(),
        "complete": False,
        "error": None,
        "rows": [],
    }

    def expired():
        write_json(
            output,
            {
                **report,
                "error": "120-second CPU measurement limit",
                "elapsed_seconds": time.perf_counter() - started,
            },
        )
        os._exit(77)

    guard = threading.Timer(120, expired)
    guard.daemon = True
    guard.start()
    try:
        for shape in SHAPES:
            report["rows"].append(measure(shape))
        assert "torch" not in sys.modules, (
            "This measurement must not import a model runtime"
        )
        report["complete"] = True
    except BaseException as error:
        report["error"] = repr(error)
        raise
    finally:
        guard.cancel()
        guard.join()
        report["elapsed_seconds"] = time.perf_counter() - started
        report["torch_imported"] = "torch" in sys.modules
        write_json(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
