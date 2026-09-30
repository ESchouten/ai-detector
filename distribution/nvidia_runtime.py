"""Stage the small NVIDIA bootstrap payload; GPU wheels are downloaded on first use."""

import json
import shutil
import subprocess
from pathlib import Path


def stage_nvidia_runtime(root: Path, destination: Path, reference: str) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("uv is required to stage the NVIDIA runtime")
    shutil.copytree(root / "distribution/nvidia", destination)
    (destination / "runtime.json").write_text(
        json.dumps({"python": (root / "detector/.python-version").read_text().strip()})
        + "\n",
        encoding="utf-8",
    )
    shutil.copy2(uv, destination / "uv.exe")
    for filename, selection in (
        ("pylock.toml", ["--extra", "nvidia", "--no-dev"]),
        ("pylock.tensorrt.toml", ["--only-group", "tensorrt"]),
    ):
        subprocess.run(
            [
                uv,
                "export",
                "--locked",
                *selection,
                "--no-emit-project",
                "--no-header",
                "--format",
                "pylock.toml",
                "--output-file",
                str(destination / filename),
            ],
            cwd=root / "detector",
            check=True,
            stdout=subprocess.DEVNULL,
        )
    app = destination / "app/aidetector"
    shutil.copytree(
        root / "detector/src/aidetector",
        app,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (app / "version.py").write_text(
        f"TYPE = 'cuda'\nREF_NAME = {json.dumps(reference)}\n", encoding="utf-8"
    )
