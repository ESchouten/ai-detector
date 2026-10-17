"""Hang at the inference import boundary to exercise real helper diagnostics."""

import sys
from importlib.abc import MetaPathFinder
from pathlib import Path
from threading import Event

from aidetector.adapters.inference import tensorrt_worker


class StalledInferenceImport(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "numpy":
            Event().wait(30)
            raise ImportError("Blocked inference import fixture expired")
        return None


tensorrt_worker.TRACE_INTERVAL = 0.05
sys.meta_path.insert(0, StalledInferenceImport())
raise SystemExit(tensorrt_worker.run_helper(Path(sys.argv[1])))
