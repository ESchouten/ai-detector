"""Build native installers from an assembled application; never install them locally."""

import argparse
import shutil
import subprocess
from pathlib import Path

from package import checksum, version_number

ASSETS = Path(__file__).parent


def macos(folder: Path, version: str) -> Path:
    from dmgbuild import build_dmg

    image = folder.parent / f"AI-Detector-{version}-macos-arm64.dmg"
    if image.exists():
        raise FileExistsError(image)
    build_dmg(
        str(image),
        "AI Detector",
        settings={
            "format": "UDZO",
            "files": [str(folder / "AI Detector.app")],
            "symlinks": {"Applications": "/Applications"},
            "hide_extensions": ["AI Detector.app"],
            "icon": str(ASSETS / "macos" / "AI Detector.icns"),
            "background": str(ASSETS / "macos" / "background.png"),
            "window_rect": ((180, 180), (660, 420)),
            "default_view": "icon-view",
            "icon_locations": {
                "AI Detector.app": (175, 210),
                "Applications": (485, 210),
            },
            "icon_size": 112,
            "text_size": 14,
            "grid_spacing": 80,
            "show_status_bar": False,
            "show_tab_view": False,
            "show_toolbar": False,
            "show_pathbar": False,
            "show_sidebar": False,
        },
    )
    checksum(image)
    return image


def windows(folder: Path, version: str) -> Path:
    output = folder.parent.resolve() / "windows-updates"
    arguments = [
        "dotnet",
        "tool",
        "run",
        "vpk",
        "--",
        "pack",
        "--packId",
        "AIDetector",
        "--packTitle",
        "AI Detector",
        "--packAuthors",
        "AI Detector contributors",
        "--packVersion",
        version,
        "--packDir",
        str(folder.resolve()),
        "--mainExe",
        "AI Detector.exe",
        "--runtime",
        "win-x64",
        "--channel",
        "win",
        "--outputDir",
        str(output),
        "--icon",
        str((ASSETS / "windows/artwork/app.ico").resolve()),
        "--shortcuts",
        "Desktop,StartMenuRoot",
        "--exclude",
        r"START HERE\.txt",
        "--noPortable",
        "--delta",
        "BestSize",
    ]
    subprocess.run(arguments, check=True)
    installer = folder.parent / f"AI-Detector-{version}-windows-x64-setup.exe"
    shutil.copy2(output / "AIDetector-win-Setup.exe", installer)
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


def build_installer(folder: Path, platform: str, version: str) -> Path:
    builder = {"macos-arm64": macos, "windows-x64": windows, "linux-x64": linux}[
        platform
    ]
    return builder(folder, version_number(version))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument(
        "--platform", choices=["windows-x64", "macos-arm64", "linux-x64"], required=True
    )
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    print(build_installer(args.folder, args.platform, args.version))
