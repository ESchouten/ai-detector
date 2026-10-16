"""Stage the small NVIDIA bootstrap payload; GPU wheels are downloaded on first use."""

import argparse
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
    # The process manager picks CUDA 13 or, for an older driver, CUDA 12.
    for filename, selection in (
        ("pylock.cuda13.toml", ["--extra", "nvidia", "--no-dev"]),
        ("pylock.tensorrt-cuda13.toml", ["--only-group", "tensorrt-cuda13"]),
        ("pylock.cuda12.toml", ["--extra", "nvidia-cuda12", "--no-dev"]),
        ("pylock.tensorrt-cuda12.toml", ["--only-group", "tensorrt-cuda12"]),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    stage_nvidia_runtime(Path(__file__).resolve().parent.parent, args.output, args.ref)
