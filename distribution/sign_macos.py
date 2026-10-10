"""Apply local ad-hoc code signatures; Sparkle separately authenticates updates."""

import argparse
import plistlib
import subprocess
from pathlib import Path

MACH_O = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def sign_app(app: Path) -> None:
    entitlements = Path(__file__).parent / "macos" / "entitlements.plist"
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    main = app / "Contents/MacOS" / info["CFBundleExecutable"]
    for file in sorted(app.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if file == main or file.is_symlink() or not file.is_file():
            continue
        with file.open("rb") as stream:
            native = stream.read(4) in MACH_O
        if not native:
            continue
        command = [
            "codesign",
            "--force",
            "--sign",
            "-",
        ]
        if file.name == "ai-detector-web":
            command += ["--entitlements", str(entitlements)]
        elif file.name == "Downloader":
            command += ["--preserve-metadata=entitlements"]
        subprocess.run([*command, str(file)], check=True)
    for bundle in sorted(
        (
            path
            for path in app.rglob("*")
            if path.suffix in {".framework", ".app", ".xpc"}
        ),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if not bundle.is_symlink():
            options = []
            if bundle.name == "Detector.app":
                options = ["--entitlements", str(entitlements)]
            elif bundle.name == "Downloader.xpc":
                options = ["--preserve-metadata=entitlements"]
            subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--sign",
                    "-",
                    *options,
                    str(bundle),
                ],
                check=True,
            )
    subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            "-",
            str(app),
        ],
        check=True,
    )
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        check=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    sign_app(args.artifact)
