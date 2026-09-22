"""Sign nested Mach-O code, then notarize and staple with release credentials."""

import argparse
import os
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


def sign_app(app: Path, identity: str) -> None:
    if not identity.startswith("Developer ID Application:"):
        raise ValueError("Release signing requires a Developer ID Application identity")
    entitlements = Path(__file__).parent / "macos" / "entitlements.plist"
    for file in sorted(app.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if file.is_symlink() or not file.is_file():
            continue
        with file.open("rb") as stream:
            native = stream.read(4) in MACH_O
        if not native:
            continue
        command = [
            "codesign",
            "--force",
            "--options",
            "runtime",
            "--timestamp",
            "--sign",
            identity,
        ]
        if file.name in {"ai-detector-web", "aidetector"}:
            command += ["--entitlements", str(entitlements)]
        subprocess.run([*command, str(file)], check=True)
    for framework in sorted(
        app.rglob("*.framework"), key=lambda item: len(item.parts), reverse=True
    ):
        if not framework.is_symlink():
            subprocess.run(
                [
                    "codesign",
                    "--force",
                    "--options",
                    "runtime",
                    "--timestamp",
                    "--sign",
                    identity,
                    str(framework),
                ],
                check=True,
            )
    subprocess.run(
        [
            "codesign",
            "--force",
            "--options",
            "runtime",
            "--timestamp",
            "--sign",
            identity,
            str(app),
        ],
        check=True,
    )
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        check=True,
    )


def notarize(artifact: Path, profile: str, staple: Path | None = None) -> None:
    subprocess.run(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(artifact),
            "--keychain-profile",
            profile,
            "--wait",
            "--timeout",
            "30m",
        ],
        check=True,
    )
    artifact = staple or artifact
    subprocess.run(["xcrun", "stapler", "staple", str(artifact)], check=True)
    subprocess.run(["xcrun", "stapler", "validate", str(artifact)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--notarize", action="store_true")
    parser.add_argument("--staple", type=Path)
    args = parser.parse_args()
    if args.notarize:
        notarize(
            args.artifact, os.environ["MACOS_NOTARY_KEYCHAIN_PROFILE"], args.staple
        )
    else:
        sign_app(args.artifact, os.environ["MACOS_SIGN_IDENTITY"])
