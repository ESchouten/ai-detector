"""Exercise Sparkle's real signer and delta tools without installing an application."""

import base64
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from package import macos_bundle
from sign_macos import sign_app
from updates import SPARKLE


@unittest.skipUnless(
    sys.platform == "darwin" and os.environ.get("SPARKLE_SDK"),
    "Requires the pinned Sparkle SDK on macOS",
)
class SparkleTest(unittest.TestCase):
    def test_signed_delta_reconstructs_the_complete_app(self):
        sdk = Path(os.environ["SPARKLE_SDK"])
        with tempfile.TemporaryDirectory(prefix="ai-detector-sparkle-") as temporary:
            root = Path(temporary)
            archives = root / "updates"
            archives.mkdir()
            # Public RFC 8032 test vector. Never touch the developer's signing keychain.
            seed = bytes.fromhex(
                "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
            )
            public = bytes.fromhex(
                "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
            )
            key = root / "test-key"
            key.write_bytes(base64.b64encode(seed))
            launcher = root / "launcher"
            shutil.copyfile("/usr/bin/true", launcher)
            launcher.chmod(0o755)
            library = os.urandom(1024 * 1024)
            for version in ("1.0.0", "1.0.1"):
                payload = macos_bundle(
                    root / version,
                    launcher,
                    version,
                    sdk,
                    "https://example.test/updates",
                    base64.b64encode(public).decode(),
                )
                (payload.parent / "Resources/library.bin").write_bytes(library)
                (payload.parent / "Resources/web.txt").write_text(version)
                runtime = payload.parent / "Helpers/Detector.app/Contents"
                (runtime / "MacOS").mkdir(parents=True)
                (runtime / "Resources").mkdir()
                shutil.copy2(launcher, runtime / "MacOS/aidetector")
                (runtime / "Resources/model.py").write_text("print('detector')\n")
                (runtime / "Info.plist").write_bytes(
                    plistlib.dumps(
                        {
                            "CFBundleIdentifier": "io.github.eschouten.ai-detector.detector",
                            "CFBundleExecutable": "aidetector",
                            "CFBundlePackageType": "APPL",
                        }
                    )
                )
                (payload / "detector").symlink_to(
                    "../Helpers/Detector.app/Contents/MacOS"
                )
                sign_app(payload.parent.parent)
                subprocess.run(
                    [
                        "ditto",
                        "-c",
                        "-k",
                        "--keepParent",
                        str(payload.parent.parent),
                        str(archives / f"{version}.zip"),
                    ],
                    check=True,
                    capture_output=True,
                )
            env = {**os.environ, "CFFIXED_USER_HOME": str(root / "cache")}
            subprocess.run(
                [
                    str(sdk / "bin/generate_appcast"),
                    "--ed-key-file",
                    str(key),
                    "--download-url-prefix",
                    "https://example.test/updates/",
                    str(archives),
                ],
                check=True,
                env=env,
            )
            feed = archives / "appcast.xml"
            subprocess.run(
                [
                    str(sdk / "bin/sign_update"),
                    "--verify",
                    "--ed-key-file",
                    str(key),
                    str(feed),
                ],
                check=True,
                capture_output=True,
            )
            item = ET.parse(feed).find("./channel/item")
            delta = item.find(f"./{{{SPARKLE}}}deltas/enclosure")
            self.assertIsNotNone(delta, "The unchanged runtime must produce a delta")
            artifact = next(archives.glob("*.delta"))
            self.assertLess(
                artifact.stat().st_size, (archives / "1.0.1.zip").stat().st_size
            )
            subprocess.run(
                [
                    str(sdk / "bin/sign_update"),
                    "--verify",
                    "--ed-key-file",
                    str(key),
                    str(artifact),
                    delta.attrib[f"{{{SPARKLE}}}edSignature"],
                ],
                check=True,
                capture_output=True,
            )
            applied = root / "applied.app"
            subprocess.run(
                [
                    str(sdk / "bin/BinaryDelta"),
                    "apply",
                    str(root / "1.0.0/AI Detector.app"),
                    str(applied),
                    str(artifact),
                ],
                check=True,
                capture_output=True,
            )
            self.assertEqual(
                (applied / "Contents/Resources/library.bin").read_bytes(), library
            )
            self.assertEqual(
                (applied / "Contents/Resources/web.txt").read_text(), "1.0.1"
            )
            info = plistlib.loads((applied / "Contents/Info.plist").read_bytes())
            self.assertEqual(info["CFBundleVersion"], "1.0.1")
            self.assertTrue(
                (
                    applied / "Contents/Frameworks/Sparkle.framework/Versions/Current"
                ).is_symlink()
            )
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(applied)],
                check=True,
                capture_output=True,
            )
            artifact.write_bytes(artifact.read_bytes() + b"tampered")
            rejected = subprocess.run(
                [
                    str(sdk / "bin/sign_update"),
                    "--verify",
                    "--ed-key-file",
                    str(key),
                    str(artifact),
                    delta.attrib[f"{{{SPARKLE}}}edSignature"],
                ],
                capture_output=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
