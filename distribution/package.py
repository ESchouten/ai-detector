"""Assemble the portable application and the payload used by native installers."""

import argparse
import base64
import hashlib
import json
import os
import plistlib
import shutil
import stat
import zipfile
from dataclasses import dataclass
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
    if not folder.is_dir():
        raise FileNotFoundError(f"Application folder does not exist: {folder}")
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
    # Detector-only builds do not use packaging dependencies.
    from semver import Version

    value = (
        version.removeprefix("app/v")
        if version.startswith("app/v")
        else version.removeprefix("v")
    )
    try:
        parsed = Version.parse(value)
    except ValueError:
        raise ValueError(
            "Version must be a semantic version, for example 1.2.3 or app/v1.2.3"
        ) from None
    return f"{parsed.major}.{parsed.minor}.{parsed.patch}"


def macos_bundle(
    folder: Path,
    launcher: Path,
    version: str,
    sparkle: Path | None = None,
    update_feed: str | None = None,
    sparkle_public_key: str | None = None,
) -> Path:
    contents = folder / "AI Detector.app" / "Contents"
    binary = contents / "MacOS"
    binary.mkdir(parents=True)
    shutil.copy2(launcher, binary / "AI Detector")
    (binary / "AI Detector").chmod(0o755)
    resources = contents / "Resources"
    resources.mkdir()
    (resources / "application.json").write_text("{}\n", encoding="utf-8")
    (binary / "application.json").symlink_to("../Resources/application.json")
    for asset in ("AI Detector.icns", "Lucide.LICENSE"):
        shutil.copy2(Path(__file__).parent / "macos" / asset, resources)
    if sparkle:
        shutil.copytree(
            sparkle / "Sparkle.framework",
            contents / "Frameworks/Sparkle.framework",
            symlinks=True,
        )
        shutil.copy2(sparkle / "LICENSE", resources / "Sparkle.LICENSE")
    updates = {}
    if update_feed:
        if not sparkle or not sparkle_public_key:
            raise ValueError(
                "Sparkle releases require the framework and public EdDSA key"
            )
        if len(base64.b64decode(sparkle_public_key, validate=True)) != 32:
            raise ValueError("Sparkle public key must contain 32 bytes")
        updates = {
            "SUFeedURL": update_feed.rstrip("/") + "/appcast.xml",
            "SUPublicEDKey": sparkle_public_key,
            "SUEnableAutomaticChecks": True,
            "SUAllowsAutomaticUpdates": False,
            "SUVerifyUpdateBeforeExtraction": True,
            "SURequireSignedFeed": True,
            # There is no Developer ID fallback: an invalid feed must stay rejected.
            "SUSignedFeedFailureExpirationInterval": 0,
        }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleIdentifier": "io.github.eschouten.ai-detector",
                "CFBundleName": "AI Detector",
                "CFBundleDisplayName": "AI Detector",
                "CFBundleExecutable": "AI Detector",
                "CFBundleIconFile": "AI Detector.icns",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": version_number(version),
                "CFBundleVersion": version_number(version),
                "LSMinimumSystemVersion": "14.0",
                "LSUIElement": True,
                "NSHighResolutionCapable": True,
                "NSLocalNetworkUsageDescription": "AI Detector connects to cameras on your local network to monitor and record events.",
                **updates,
            },
            stream,
        )
    return binary


def copy_windows_launcher(launcher: Path, payload: Path) -> None:
    for file in launcher.iterdir():
        if (
            file.suffix in {".exe", ".dll", ".config"}
            or file.name == "ThirdPartyNotices.txt"
        ):
            shutil.copy2(file, payload)
    shutil.copy2(Path(__file__).parent / "macos" / "Lucide.LICENSE", payload)


@dataclass(frozen=True)
class PackageInputs:
    detector: Path
    web: Path
    ffmpeg: Path
    output: Path
    platform: str
    image: str | None = None
    version: str = "0.0.0"
    mac_launcher: Path | None = None
    windows_launcher: Path | None = None
    sparkle: Path | None = None
    update_feed: str | None = None
    sparkle_public_key: str | None = None


def validate_inputs(inputs: PackageInputs) -> None:
    if inputs.platform == "macos-arm64":
        validate_macos_inputs(inputs)
    if inputs.platform == "windows-x64" and inputs.windows_launcher is None:
        raise ValueError("Windows packages require the compiled native launcher")
    version_number(inputs.version)
    if inputs.update_feed and not inputs.update_feed.startswith("https://"):
        raise ValueError("Release update feeds must use HTTPS")
    if inputs.update_feed and (
        not inputs.sparkle_public_key
        or len(base64.b64decode(inputs.sparkle_public_key, validate=True)) != 32
    ):
        raise ValueError("Release updates require the public Ed25519 key")


def validate_macos_inputs(inputs: PackageInputs) -> None:
    if inputs.mac_launcher is None or inputs.sparkle is None:
        raise ValueError(
            "macOS packages require the compiled native app launcher and Sparkle SDK"
        )
    if not (inputs.detector / "Contents/MacOS/aidetector").is_file():
        raise ValueError("macOS packages require PyInstaller's aidetector.app bundle")


def assemble_macos(inputs: PackageInputs, folder: Path) -> None:
    payload = macos_bundle(
        folder,
        inputs.mac_launcher,
        inputs.version,
        inputs.sparkle,
        inputs.update_feed,
        inputs.sparkle_public_key,
    )
    shutil.copytree(
        inputs.detector, payload.parent / "Helpers/Detector.app", symlinks=True
    )
    (payload / "detector").symlink_to("../Helpers/Detector.app/Contents/MacOS")
    copy_payload_files(inputs, payload, "ai-detector-web", "ffmpeg")


def assemble_windows(inputs: PackageInputs, folder: Path) -> None:
    shutil.copytree(inputs.detector, folder / "detector", symlinks=True)
    copy_windows_launcher(inputs.windows_launcher, folder)
    copy_payload_files(inputs, folder, "ai-detector-web.exe", "ffmpeg.exe")


def assemble_linux(inputs: PackageInputs, folder: Path) -> None:
    shutil.copytree(inputs.detector, folder / "detector", symlinks=True)
    copy_payload_files(inputs, folder, "AI Detector", "ffmpeg")


def copy_payload_files(
    inputs: PackageInputs, payload: Path, launch: str, encoder: str
) -> None:
    shutil.copy2(inputs.web, payload / launch)
    (payload / launch).chmod(0o755)
    (payload / "bin").mkdir()
    shutil.copy2(inputs.ffmpeg, payload / "bin" / encoder)
    (payload / "bin" / encoder).chmod(0o755)
    metadata = {"dockerImage": inputs.image} if inputs.image else {}
    if inputs.update_feed and inputs.platform == "windows-x64":
        metadata["updateFeed"] = inputs.update_feed
        metadata["updatePublicKey"] = inputs.sparkle_public_key
    (payload / "application.json").write_text(
        json.dumps(metadata) + "\n", encoding="utf-8"
    )


def assemble_package(inputs: PackageInputs) -> Path:
    validate_inputs(inputs)
    assemble = {
        "macos-arm64": assemble_macos,
        "windows-x64": assemble_windows,
        "linux-x64": assemble_linux,
    }[inputs.platform]
    inputs.output.mkdir(parents=True, exist_ok=True)
    folder = inputs.output / f"AI-Detector-{inputs.platform}"
    folder.mkdir()
    assemble(inputs, folder)
    (folder / "START HERE.txt").write_text(INSTRUCTIONS, encoding="utf-8")
    return folder


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
        "--sparkle", type=Path, help="Extracted, pinned Sparkle distribution"
    )
    parser.add_argument(
        "--update-feed", help="HTTPS directory containing this channel's update feeds"
    )
    parser.add_argument("--sparkle-public-key")
    parser.add_argument(
        "--windows-launcher", type=Path, help="Compiled Windows launcher folder"
    )
    parser.add_argument(
        "--image", help="Matching image digest; omit for native-only previews"
    )
    print(assemble_package(PackageInputs(**vars(parser.parse_args()))))
