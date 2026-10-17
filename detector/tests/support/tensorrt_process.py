"""Exercise builder process supervision without requiring NVIDIA hardware."""

import json
import os
import sys
from pathlib import Path
from threading import Event

request = json.loads(Path(sys.argv[-1]).read_text())
checkpoint = Path(request["checkpoint"])
checkpoint.with_suffix(".engine").write_bytes(b"engine-from-" + checkpoint.read_bytes())
mode = os.environ.get("TENSORRT_TEST_MODE", "ready")
print("GPU builder fixture: " + mode, flush=True)
if mode == "failed":
    raise SystemExit(2)
if mode == "crashed":
    os._exit(7)
if mode == "blocked":
    Event().wait(30)
