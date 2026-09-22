"""Assemble one download containing the browser app and its native detector."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def package(
    detector: Path,
    web: Path,
    ffmpeg: Path,
    output: Path,
    platform: str,
    image: str | None,
) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    name = f"AI-Detector-{platform}"
    folder = output / name
    folder.mkdir()
    shutil.copytree(detector, folder / "detector")
    if platform == "windows-x64":
        launch = "AI Detector.exe"
    elif platform == "macos-arm64":
        launch = "AI Detector.command"
    else:
        launch = "AI Detector"
    shutil.copy2(web, folder / launch)
    (folder / launch).chmod(0o755)
    (folder / "bin").mkdir()
    encoder = "ffmpeg.exe" if platform == "windows-x64" else "ffmpeg"
    shutil.copy2(ffmpeg, folder / "bin" / encoder)
    (folder / "application.json").write_text(
        json.dumps({"dockerImage": image} if image else {}) + "\n", encoding="utf-8"
    )
    (folder / "START HERE.txt").write_text(
        f"AI Detector\n\n1. Extract this entire download.\n2. Open {launch}.\n"
        "3. Follow the setup in your browser. If it does not open, visit http://localhost:8765/.\n"
        "Later launches open Detections.\n\n"
        "Keep all downloaded files together. You do not need to open the detector separately.\n"
        "Keep the application and computer running while detection is needed.\n"
        "Settings and recordings are stored in your user account, outside this download.\n"
        "The setup page shows their location. Keep that folder when updating the application.\n"
        "On NVIDIA computers, setup checks Docker and links to any missing prerequisites.\n"
        "Use Stop detection before closing the application.\n",
        encoding="utf-8",
    )
    archive = Path(shutil.make_archive(str(output / name), "zip", output, name))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("detector", "web", "ffmpeg", "output"):
        parser.add_argument(f"--{argument}", type=Path, required=True)
    parser.add_argument(
        "--platform",
        choices=["windows-x64", "macos-arm64", "linux-x64"],
        required=True,
    )
    parser.add_argument(
        "--image", help="Matching image digest; omit for a native-only local preview"
    )
    print(package(**vars(parser.parse_args())))
