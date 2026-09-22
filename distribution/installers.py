"""Build native installers from an assembled application; never install them locally."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from package import INSTRUCTIONS, checksum, version_number

ASSETS = Path(__file__).parent


def macos(folder: Path, version: str) -> Path:
    staging = folder.parent / "macos-dmg"
    staging.mkdir()
    shutil.copytree(
        folder / "AI Detector.app", staging / "AI Detector.app", symlinks=True
    )
    (staging / "Applications").symlink_to("/Applications")
    (staging / "READ ME.txt").write_text(
        "Drag AI Detector to Applications, then open it there.\n"
        "The menu bar provides Open dashboard, Open at login and Quit.\n\n"
        + INSTRUCTIONS,
        encoding="utf-8",
    )
    image = folder.parent / f"AI-Detector-{version}-macos-arm64.dmg"
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "AI Detector",
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(image),
        ],
        check=True,
    )
    checksum(image)
    return image


def windows(folder: Path, version: str, *, signed: bool) -> Path:
    output = folder.parent.resolve()
    arguments = [
        os.environ.get("ISCC", r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        f"/DSourceDir={folder.resolve()}",
        f"/DOutputDir={output}",
        f"/DVersion={version}",
    ]
    if signed:
        arguments += ["/DSigned", "/Srelease=" + os.environ["INNO_SIGN_COMMAND"]]
    arguments.append(str(ASSETS / "windows" / "installer.iss"))
    subprocess.run(arguments, check=True)
    installer = output / f"AI-Detector-{version}-windows-x64-setup.exe"
    checksum(installer)
    return installer


def linux_tree(folder: Path, version: str) -> Path:
    root = folder.parent / "debian"
    shutil.copytree(folder, root / "opt" / "ai-detector", symlinks=True)
    desktop = root / "usr" / "share" / "applications"
    desktop.mkdir(parents=True)
    shutil.copy2(ASSETS / "linux" / "ai-detector.desktop", desktop)
    # The desktop's startup application preferences can disable this standard entry.
    autostart = root / "etc" / "xdg" / "autostart"
    autostart.mkdir(parents=True)
    shutil.copy2(ASSETS / "linux" / "ai-detector.desktop", autostart)
    control = root / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(
        f"Package: ai-detector\nVersion: {version}\nArchitecture: amd64\n"
        "Maintainer: AI Detector contributors\n"
        "Section: video\nPriority: optional\n"
        "Depends: libc6 (>= 2.35), libstdc++6, libgl1, libglib2.0-0, libgomp1, xdg-utils, psmisc, gnome-startup-applications\n"
        "Homepage: https://github.com/ESchouten/ai-detector\n"
        "Description: Local camera monitoring and recordings\n"
        " Bundled desktop application for Ubuntu 22.04 and 24.04 amd64.\n"
        " Opens at desktop login; use Startup Applications to disable automatic opening.\n"
        " Settings and recordings remain in the user's data directory on removal.\n",
        encoding="utf-8",
    )
    shutil.copy2(ASSETS / "linux" / "prerm", control / "prerm")
    (control / "prerm").chmod(0o755)
    (control / "conffiles").write_text(
        "/etc/xdg/autostart/ai-detector.desktop\n", encoding="utf-8"
    )
    return root


def linux(folder: Path, version: str) -> Path:
    root = linux_tree(folder, version)
    subprocess.run(
        [
            "desktop-file-validate",
            str(root / "usr/share/applications/ai-detector.desktop"),
        ],
        check=True,
    )
    artifact = folder.parent / f"AI-Detector-{version}-linux-amd64.deb"
    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(root), str(artifact)],
        check=True,
    )
    checksum(artifact)
    return artifact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument(
        "--platform", choices=["windows-x64", "macos-arm64", "linux-x64"], required=True
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--signed", action="store_true")
    args = parser.parse_args()
    version = version_number(args.version)
    if args.platform == "macos-arm64":
        print(macos(args.folder, version))
    elif args.platform == "windows-x64":
        print(windows(args.folder, version, signed=args.signed))
    else:
        print(linux(args.folder, version))
