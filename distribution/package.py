"""Assemble the portable application and the payload used by native installers."""

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import zipfile
from pathlib import Path

INSTRUCTIONS = """AI Detector

Open AI Detector and follow the setup in your browser.
Closing the browser leaves monitoring active. Open AI Detector again to return.
Pause monitoring in the dashboard only when you want it to stay paused.
Quitting the application stops monitoring until you open it again; enabled monitoring resumes.
Keep this computer awake while monitoring is needed.

Settings and recordings are stored in your user account, outside this application.
The dashboard shows their location. Updates and uninstalling the program preserve them.
Automatic opening at desktop login is different from monitoring before login.
"""


def checksum(artifact: Path) -> Path:
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    destination = artifact.with_suffix(artifact.suffix + ".sha256")
    destination.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
    return destination


def archive(folder: Path) -> Path:
    result = folder.with_suffix(".zip")
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as output:
        for directory, folders, files in os.walk(folder):
            for name in sorted(folders + files):
                file = Path(directory) / name
                relative = file.relative_to(folder.parent).as_posix()
                if file.is_symlink():
                    info = zipfile.ZipInfo(relative)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    output.writestr(info, os.readlink(file))
                else:
                    output.write(file, relative)
    checksum(result)
    return result


def version_number(version: str) -> str:
    match = re.fullmatch(r"(?:app/v|v)?(\d+\.\d+\.\d+)(?:[-+][\w.-]+)?", version)
    if not match:
        raise ValueError(
            "Version must be a semantic version, for example 1.2.3 or app/v1.2.3"
        )
    return match[1]


def macos_bundle(folder: Path, launcher: Path, version: str) -> Path:
    contents = folder / "AI Detector.app" / "Contents"
    binary = contents / "MacOS"
    binary.mkdir(parents=True)
    shutil.copy2(launcher, binary / "AI Detector")
    (binary / "AI Detector").chmod(0o755)
    (contents / "Resources").mkdir()
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleIdentifier": "io.github.eschouten.ai-detector",
                "CFBundleName": "AI Detector",
                "CFBundleDisplayName": "AI Detector",
                "CFBundleExecutable": "AI Detector",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": version_number(version),
                "CFBundleVersion": version_number(version),
                "LSMinimumSystemVersion": "14.0",
                "LSUIElement": True,
                "NSHighResolutionCapable": True,
                "NSLocalNetworkUsageDescription": "AI Detector connects to cameras on your local network to monitor and record events.",
            },
            stream,
        )
    return binary


def package(
    detector: Path,
    web: Path,
    ffmpeg: Path,
    output: Path,
    platform: str,
    image: str | None,
    version: str = "0.0.0",
    mac_launcher: Path | None = None,
) -> Path:
    if platform == "macos-arm64" and mac_launcher is None:
        raise ValueError("macOS packages require the compiled native app launcher")
    version_number(version)
    output.mkdir(parents=True, exist_ok=True)
    folder = output / f"AI-Detector-{platform}"
    folder.mkdir()
    payload = (
        macos_bundle(folder, mac_launcher, version)
        if platform == "macos-arm64"
        else folder
    )
    shutil.copytree(detector, payload / "detector", symlinks=True)
    launch = "AI Detector.exe" if platform == "windows-x64" else "AI Detector"
    if platform == "macos-arm64":
        launch = "ai-detector-web"
    shutil.copy2(web, payload / launch)
    (payload / launch).chmod(0o755)
    (payload / "bin").mkdir()
    encoder = "ffmpeg.exe" if platform == "windows-x64" else "ffmpeg"
    shutil.copy2(ffmpeg, payload / "bin" / encoder)
    (payload / "bin" / encoder).chmod(0o755)
    (payload / "application.json").write_text(
        json.dumps({"dockerImage": image} if image else {}) + "\n", encoding="utf-8"
    )
    (folder / "START HERE.txt").write_text(INSTRUCTIONS, encoding="utf-8")
    return archive(folder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("detector", "web", "ffmpeg", "output"):
        parser.add_argument(f"--{argument}", type=Path, required=True)
    parser.add_argument(
        "--platform", choices=["windows-x64", "macos-arm64", "linux-x64"], required=True
    )
    parser.add_argument("--version", default="0.0.0")
    parser.add_argument("--mac-launcher", type=Path)
    parser.add_argument(
        "--image", help="Matching image digest; omit for native-only previews"
    )
    print(package(**vars(parser.parse_args())))
