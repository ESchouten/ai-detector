"""Exercise Sparkle's real signer and delta tools without installing an application."""

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from fixtures.keys import PRIVATE_KEY, PUBLIC_KEY
from package import macos_bundle
from sign_macos import sign_app
from update_channels import merge_macos, sparkle_signature
from updates import SPARKLE, generate_macos_feed, mac_items


@unittest.skipUnless(
    sys.platform == "darwin" and os.environ.get("SPARKLE_SDK"),
    "Requires the pinned Sparkle SDK on macOS",
)
class SparkleTest(unittest.TestCase):
    def test_signed_delta_reconstructs_the_complete_app(self):
        self.check_delta("1.0.0", "1.0.1", "app-updates")

    def test_preview_delta_preserves_its_channel(self):
        self.check_delta("0.0.41", "0.0.42", "app-preview-updates")

    def test_a_newer_preview_can_follow_an_official_display_version(self):
        self.check_delta("2.0.0", "0.0.43", "app-update-channels", ("42.0.0", "43.0.0"))

    def check_delta(self, previous: str, current: str, channel: str, builds=None):
        builds = builds or (previous, current)
        sdk = Path(os.environ["SPARKLE_SDK"])
        with tempfile.TemporaryDirectory(prefix="ai-detector-sparkle-") as temporary:
            root = Path(temporary)
            archives = root / "updates"
            archives.mkdir()
            key = root / "test-key"
            key.write_text(PRIVATE_KEY)
            launcher = root / "launcher"
            shutil.copyfile("/usr/bin/true", launcher)
            launcher.chmod(0o755)
            library = os.urandom(1024 * 1024)
            for version, build in zip((previous, current), builds, strict=True):
                payload = macos_bundle(
                    root / version,
                    launcher,
                    version,
                    sdk,
                    f"https://example.test/{channel}",
                    PUBLIC_KEY,
                    build_version=build,
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
                with patch.dict(
                    os.environ,
                    {
                        "CFFIXED_USER_HOME": str(root / "cache"),
                        "SPARKLE_PRIVATE_KEY": key.read_text(),
                    },
                ):
                    generate_macos_feed(
                        archives,
                        build,
                        f"https://example.test/releases/{version}",
                        sdk,
                    )
                if version == previous:
                    previous_feed = (archives / "appcast.xml").read_bytes()
            feed = archives / "appcast.xml"
            self.check_release_urls(feed, previous_feed, builds[0], builds[1], current)
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
            self.assertNotIn(" ", artifact.name)
            self.assertEqual(
                delta.get("url"),
                f"https://example.test/releases/{current}/"
                + urllib.parse.quote(artifact.name),
            )
            self.assertLess(
                artifact.stat().st_size, (archives / f"{current}.zip").stat().st_size
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
                    str(root / previous / "AI Detector.app"),
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
                (applied / "Contents/Resources/web.txt").read_text(), current
            )
            self.check_bundle(applied, builds[1], current, channel)
            self.check_rejected_delta(
                sdk, key, artifact, delta.attrib[f"{{{SPARKLE}}}edSignature"]
            )

            self.check_channel_signature(sdk, feed)

    def check_bundle(self, applied, build, version, channel):
        info = plistlib.loads((applied / "Contents/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleVersion"], build)
        self.assertEqual(info["CFBundleShortVersionString"], version)
        self.assertEqual(
            info["SUFeedURL"], f"https://example.test/{channel}/appcast.xml"
        )
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

    def check_rejected_delta(self, sdk, key, artifact, signature):
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
        rejected = subprocess.run(
            [
                str(sdk / "bin/sign_update"),
                "--verify",
                "--ed-key-file",
                str(key),
                str(artifact),
                signature,
            ],
            capture_output=True,
        )
        self.assertNotEqual(rejected.returncode, 0)

    def check_channel_signature(self, sdk, feed):
        # Changing channel metadata must invalidate the combined feed signature.
        combined = feed.with_name("channels.xml")
        combined.write_bytes(merge_macos(feed.read_bytes(), None, "preview"))
        with patch.dict(os.environ, {"SPARKLE_PRIVATE_KEY": PRIVATE_KEY}):
            sparkle_signature(sdk, combined)
            sparkle_signature(sdk, combined, verify=True)
            combined.write_bytes(
                combined.read_bytes().replace(b">preview<", b">stable<")
            )
            with self.assertRaises(subprocess.CalledProcessError):
                sparkle_signature(sdk, combined, verify=True)

    def check_release_urls(self, feed, previous_feed, previous, current, display):
        items = dict(mac_items(feed.read_bytes()))
        self.assertEqual(
            items[previous].attrib,
            dict(mac_items(previous_feed))[previous].attrib,
        )
        self.assertEqual(
            items[current].get("url"),
            f"https://example.test/releases/{display}/{display}.zip",
        )
