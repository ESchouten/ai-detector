"""Release feed contracts; all downloads use a temporary local HTTP server."""

import hashlib
import http.server
import json
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path

from fixtures.keys import PRIVATE_KEY, PUBLIC_KEY
from release_config import release_config
from release_signatures import sign_feed, verify_feed
from updates import mac_items, newer_than, numeric_version, prepare, windows


class UpdateFeedTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host = self.root / "host"
        self.host.mkdir()
        self.output = self.root / "output"
        self.output.mkdir()
        handler = partial(
            http.server.SimpleHTTPRequestHandler, directory=str(self.host)
        )
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}"

    def test_numeric_versions_cannot_downgrade_or_promote_prereleases(self):
        newer_than("1.10.0", ["1.9.0"])
        for bad in ("1.0", "01.0.0", "1.0.0-rc.1", "1.0.0+test"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                numeric_version(bad)
        for version in ("1.0.0", "0.9.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                newer_than(version, ["1.0.0"])

    def test_first_release_has_no_delta_base(self):
        prepare(self.output, "windows-x64", "1.0.0", self.url)
        self.assertEqual(list((self.output / "windows-updates").iterdir()), [])

    def test_windows_downloads_verified_base_and_keeps_immutable_urls(self):
        content = b"previous full package"
        (self.host / "old.nupkg").write_bytes(content)
        previous = {
            "PackageId": "AIDetector",
            "Size": len(content),
            "Version": "1.0.0",
            "Type": "Full",
            "FileName": self.url + "/old.nupkg",
            "SHA256": hashlib.sha256(content).hexdigest(),
        }
        (self.host / "releases.win.json").write_bytes(
            sign_feed(
                json.dumps({"Assets": [previous]}).encode(), PRIVATE_KEY, PUBLIC_KEY
            )
        )
        prepare(self.output, "windows-x64", "1.0.1", self.url, PUBLIC_KEY)
        folder = self.output / "windows-updates"
        self.assertEqual((folder / "old.nupkg").read_bytes(), content)
        current = []
        for kind in ("Full", "Delta"):
            name = f"1.0.1-{kind}.nupkg"
            (folder / name).write_bytes(kind.encode())
            current.append(
                {
                    "PackageId": "AIDetector",
                    "Version": "1.0.1",
                    "Type": kind,
                    "FileName": name,
                    "SHA256": hashlib.sha256(kind.encode()).hexdigest(),
                    "Size": len(kind),
                }
            )
        (folder / "releases.win.json").write_text(
            json.dumps({"Assets": [previous, *current]})
        )
        windows(
            self.output,
            "1.0.1",
            "https://github.com/example/app/releases/download/app/v1.0.1",
            PRIVATE_KEY,
            PUBLIC_KEY,
        )
        result = json.loads(
            verify_feed((self.output / "releases.win.json").read_bytes(), PUBLIC_KEY)
        )["Assets"]
        self.assertEqual(result[0], previous)
        self.assertTrue(
            all(
                asset["FileName"].startswith(
                    "https://github.com/example/app/releases/download/app/v1.0.1/"
                )
                for asset in result[1:]
            )
        )
        self.assertFalse((self.output / "old.nupkg").exists())
        self.assertEqual((self.output / "1.0.1-Delta.nupkg").read_bytes(), b"Delta")

    def test_corrupt_previous_package_stops_the_release(self):
        (self.host / "old.nupkg").write_bytes(b"wrong bytes")
        (self.host / "releases.win.json").write_text(
            json.dumps(
                {
                    "Assets": [
                        {
                            "Version": "1.0.0",
                            "Type": "Full",
                            "FileName": "old.nupkg",
                            "SHA256": "0" * 64,
                        }
                    ]
                }
            )
        )
        feed = self.host / "releases.win.json"
        feed.write_bytes(sign_feed(feed.read_bytes(), PRIVATE_KEY, PUBLIC_KEY))
        with self.assertRaisesRegex(ValueError, "checksum failed"):
            prepare(self.output, "windows-x64", "1.0.1", self.url, PUBLIC_KEY)

    def test_preview_feed_advances_without_reading_or_changing_the_stable_feed(self):
        stable = self.host / "app-updates"
        preview = self.host / "app-preview-updates"
        stable.mkdir()
        preview.mkdir()
        sentinel = b"Stable feed must not be read, replaced or used for delta inputs"
        (stable / "releases.win.json").write_bytes(sentinel)
        for number in (42, 43):
            release = release_config(
                f"refs/tags/app/test-{number}", "example/app", number, number
            )
            output = self.root / str(number)
            output.mkdir()
            prepare(
                output,
                "windows-x64",
                release["version"],
                self.url + "/" + release["feed_tag"],
                PUBLIC_KEY,
            )
            folder = output / "windows-updates"
            name = f"AIDetector-{release['version']}-full.nupkg"
            content = f"preview {number}".encode()
            (folder / name).write_bytes(content)
            (folder / "releases.win.json").write_text(
                json.dumps(
                    {
                        "Assets": [
                            {
                                "PackageId": "AIDetector",
                                "Version": release["version"],
                                "Type": "Full",
                                "FileName": name,
                                "SHA256": hashlib.sha256(content).hexdigest(),
                                "Size": len(content),
                            }
                        ]
                    }
                )
            )
            windows(output, release["version"], self.url, PRIVATE_KEY, PUBLIC_KEY)
            (self.host / name).write_bytes(content)
            (preview / "releases.win.json").write_bytes(
                (output / "releases.win.json").read_bytes()
            )
        feed = json.loads(
            verify_feed((preview / "releases.win.json").read_bytes(), PUBLIC_KEY)
        )
        self.assertEqual(
            [asset["Version"] for asset in feed["Assets"]], ["0.0.42", "0.0.43"]
        )
        self.assertEqual((stable / "releases.win.json").read_bytes(), sentinel)
        self.assertEqual(
            (
                self.root / "43/windows-updates/AIDetector-0.0.42-full.nupkg"
            ).read_bytes(),
            b"preview 42",
        )

    def test_sparkle_preserves_old_feed_urls_and_downloads_only_two_bases(self):
        items = []
        for version in ("1.0.0", "1.2.0", "1.1.0"):
            name = f"AI-Detector-{version}.dmg"
            (self.host / name).write_bytes(version.encode())
            items.append(
                f'<item><sparkle:version>{version}</sparkle:version><enclosure url="{self.url}/{name}" /></item>'
            )
        feed = (
            '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel>'
            + "".join(items)
            + "</channel></rss>"
        )
        (self.host / "appcast.xml").write_text(feed)
        prepare(self.output, "macos-arm64", "1.3.0", self.url)
        folder = self.output / "macos-updates"
        self.assertEqual((folder / "appcast.xml").read_text(), feed)
        self.assertEqual(
            {path.name for path in folder.glob("*.dmg")},
            {"AI-Detector-1.2.0.dmg", "AI-Detector-1.1.0.dmg"},
        )
        self.assertEqual(
            [version for version, _ in mac_items(feed.encode())],
            ["1.2.0", "1.1.0", "1.0.0"],
        )
