"""Cold packaged-startup contract; scans real system fonts on first launch."""

import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

SOURCE = Path(__file__).resolve().parents[2] / "src"


def test_packaged_startup_reuses_the_font_cache_in_the_data_directory(tmp_path):
    image = tmp_path / "input.png"
    assert cv2.imwrite(str(image), np.zeros((24, 32, 3), dtype=np.uint8))
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"detectors": [{"detection": {"source": str(image)}}]})
    )
    output = tmp_path / "data"
    script = (
        "import sys; sys.frozen = True; "
        "from aidetector.cli import main; "
        "result = main(sys.argv[1:]); "
        "import matplotlib.font_manager; "
        "raise SystemExit(result)"
    )
    timestamps = []
    for launch in range(2):
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                "--config",
                str(config),
                "--data-dir",
                str(output),
            ],
            env={
                **os.environ,
                "PYTHONPATH": str(SOURCE),
                "MPLCONFIGDIR": str(tmp_path / f"pyinstaller-temporary-{launch}"),
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == 0, process.stderr
        [cache] = (output / "cache" / "matplotlib").glob("fontlist-*.json")
        timestamps.append(cache.stat().st_mtime_ns)
        assert not (tmp_path / f"pyinstaller-temporary-{launch}").exists()
    assert timestamps[0] == timestamps[1]
