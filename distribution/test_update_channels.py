"""Channel publication keeps immutable assets and authenticates selection metadata."""

import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from fixtures.keys import PRIVATE_KEY, PUBLIC_KEY
from release_signatures import sign_feed, verify_feed
from update_channels import merge_macos, publish
from updates import SPARKLE


class ChannelFeedTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def publish_windows(self, current: bytes, fetched: bytes):
        (self.root / "releases.win.json").write_bytes(
            sign_feed(current, PRIVATE_KEY, PUBLIC_KEY)
        )
        with (
            patch.dict(
                os.environ,
                {"SPARKLE_PRIVATE_KEY": PRIVATE_KEY, "SPARKLE_PUBLIC_KEY": PUBLIC_KEY},
            ),
            patch("update_channels.fetch_feed", return_value=fetched) as fetch,
        ):
            publish(
                self.root,
                "windows-x64",
                "preview",
                "https://example.test/app-preview-updates",
                "43.0.0",
                None,
            )
        return fetch

    def test_sparkle_opt_in_keeps_official_releases_in_the_same_feed(self):
        def feed(version):
            return f'<rss xmlns:sparkle="{SPARKLE}"><channel><item><sparkle:version>{version}</sparkle:version><enclosure url="https://example.test/{version}.dmg" sparkle:edSignature="archive-signature" /></item></channel></rss>'.encode()

        for channel in ("preview", "stable"):
            with self.subTest(channel=channel):
                combined = ET.fromstring(
                    merge_macos(feed("43.0.0"), feed("42.0.0"), channel)
                )
                items = combined.findall("./channel/item")
                self.assertEqual(len(items), 2)
                self.assertEqual(
                    [item.findtext(f"{{{SPARKLE}}}channel") for item in items],
                    ["preview", None] if channel == "preview" else [None, "preview"],
                )
                self.assertEqual(
                    items[1].find("enclosure").attrib["url"],
                    "https://example.test/42.0.0.dmg",
                )
                self.assertEqual(
                    items[1].find("enclosure").attrib[f"{{{SPARKLE}}}edSignature"],
                    "archive-signature",
                )

    def test_windows_combines_signed_channels_and_keeps_official_releases(self):
        stable = {
            "Assets": [
                {
                    "Version": "2.0.0",
                    "Type": "Full",
                    "BuildVersion": "42.0.0",
                    "ReleaseChannel": "stable",
                    "FileName": "https://example.test/stable.nupkg",
                }
            ]
        }
        preview = {
            "Assets": [
                {
                    "Version": "0.0.43",
                    "Type": "Full",
                    "BuildVersion": "43.0.0",
                    "ReleaseChannel": "preview",
                    "FileName": "https://example.test/preview.nupkg",
                }
            ]
        }
        fetch = self.publish_windows(
            json.dumps(preview).encode(),
            sign_feed(json.dumps(stable).encode(), PRIVATE_KEY, PUBLIC_KEY),
        )
        fetch.assert_called_once_with(
            "https://example.test/app-updates/releases.win.json"
        )
        assets = json.loads(
            verify_feed(
                (self.root / "channel-updates/releases.win.json").read_bytes(),
                PUBLIC_KEY,
            )
        )["Assets"]
        self.assertEqual(
            [(asset["ReleaseChannel"], asset["BuildVersion"]) for asset in assets],
            [("preview", "43.0.0"), ("stable", "42.0.0")],
        )
        self.assertEqual(assets[1]["FileName"], stable["Assets"][0]["FileName"])

    def test_invalid_other_channel_cannot_be_promoted_to_a_signed_feed(self):
        with self.assertRaises(KeyError):
            self.publish_windows(b'{"Assets":[]}', b'{"Assets":[]}')
        self.assertFalse((self.root / "channel-updates/releases.win.json").exists())

    def test_build_number_cannot_go_backwards_across_channels(self):
        previous = sign_feed(
            b'{"Assets":[{"BuildVersion":"44.0.0"}]}', PRIVATE_KEY, PUBLIC_KEY
        )
        with self.assertRaisesRegex(ValueError, "advance across both"):
            self.publish_windows(b'{"Assets":[]}', previous)
        self.assertFalse((self.root / "channel-updates/releases.win.json").exists())

    def test_first_channel_release_publishes_without_an_official_release(self):
        (self.root / "appcast.xml").write_bytes(
            f'<rss xmlns:sparkle="{SPARKLE}"><channel><item><sparkle:version>43.0.0</sparkle:version></item></channel></rss>'.encode()
        )
        with (
            patch("update_channels.fetch_feed", return_value=None),
            patch("update_channels.sparkle_signature") as sign,
        ):
            publish(
                self.root,
                "macos-arm64",
                "preview",
                "https://example.test/app-preview-updates",
                "43.0.0",
                self.root,
            )
        combined = self.root / "channel-updates/appcast.xml"
        sign.assert_called_once_with(self.root, combined)
        item = ET.parse(combined).find("./channel/item")
        self.assertEqual(item.findtext(f"{{{SPARKLE}}}channel"), "preview")
