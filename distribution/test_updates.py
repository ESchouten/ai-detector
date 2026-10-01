"""Release feed contracts; all downloads use a temporary local HTTP server."""

import hashlib
import http.server
import json
import tempfile
import threading
import unittest
import urllib.error
from functools import partial
from pathlib import Path

from fixtures.keys import PRIVATE_KEY, PUBLIC_KEY
from release_config import release_config
from release_signatures import sign_feed, verify_feed
from updates import download, mac_items, newer_than, numeric_version, prepare, windows


class ReleaseHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/error/"):
            self.send_error(int(self.path.rsplit("/", 1)[1]))
        else:
            super().do_GET()


class UpdateFeedTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host = self.root / "host"
        self.host.mkdir()
        self.output = self.root / "output"
        self.output.mkdir()
        handler = partial(ReleaseHandler, directory=str(self.host))
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

    def test_official_version_bump_cannot_reuse_an_older_build_number(self):
        (self.output / "windows-updates").mkdir()
        (self.output / "windows-updates/releases.win.json").write_text('{"Assets":[]}')
        (self.output / "previous-windows-feed.json").write_text(
            json.dumps({"Assets": [{"Version": "1.0.0", "BuildVersion": "43.0.0"}]})
        )
        with self.assertRaisesRegex(ValueError, "must be newer"):
            windows(
                self.output,
                "2.0.0",
                self.url,
                PRIVATE_KEY,
                PUBLIC_KEY,
                "42.0.0",
                "stable",
            )

    def test_first_release_has_no_delta_base(self):
        prepare(self.output, "windows-x64", "1.0.0", self.url)
        self.assertEqual(list((self.output / "windows-updates").iterdir()), [])

    def test_download_failures_other_than_missing_archives_stop_the_build(self):
        for code in (403, 429, 500, 503):
            with (
                self.subTest(code=code),
                self.assertRaises(urllib.error.HTTPError) as error,
            ):
                download(f"{self.url}/error/{code}", self.output / "previous.dmg")
            self.assertEqual(error.exception.code, code)
            self.assertFalse((self.output / "previous.dmg").exists())

    def test_windows_release_history_does_not_require_old_packages_to_be_available(
        self,
    ):
        asset = {
            "Version": "1.0.0",
            "Type": "Full",
            "FileName": "removed.nupkg",
            "SHA256": "0" * 64,
        }
        (self.host / "releases.win.json").write_bytes(
            sign_feed(json.dumps({"Assets": [asset]}).encode(), PRIVATE_KEY, PUBLIC_KEY)
        )
        prepare(self.output, "windows-x64", "1.0.1", self.url, PUBLIC_KEY)
        self.assertEqual(list((self.output / "windows-updates").iterdir()), [])
        self.assertEqual(
            json.loads((self.output / "previous-windows-feed.json").read_bytes()),
            {"Assets": [asset]},
        )

    def test_windows_keeps_immutable_full_packages_without_downloading_delta_bases(
        self,
    ):
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
                json.dumps(
                    {"Assets": [previous, {**previous, "Type": "Delta"}]}
                ).encode(),
                PRIVATE_KEY,
                PUBLIC_KEY,
            )
        )
        prepare(self.output, "windows-x64", "1.0.1", self.url, PUBLIC_KEY)
        folder = self.output / "windows-updates"
        self.assertEqual(list(folder.iterdir()), [])
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
        self.assertEqual([asset["Type"] for asset in result], ["Full", "Full"])
        self.assertEqual((self.output / "1.0.1-Full.nupkg").read_bytes(), b"Full")
        self.assertFalse((self.output / "1.0.1-Delta.nupkg").exists())

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
        self.assertFalse(
            (self.root / "43/windows-updates/AIDetector-0.0.42-full.nupkg").exists()
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
        self.assertEqual(
            [
                enclosure.attrib
                for _, enclosure in mac_items((folder / "appcast.xml").read_bytes())
            ],
            [enclosure.attrib for _, enclosure in mac_items(feed.encode())[:2]],
        )
        self.assertEqual(
            {path.name for path in folder.glob("*.dmg")},
            {"AI-Detector-1.2.0.dmg", "AI-Detector-1.1.0.dmg"},
        )
        self.assertEqual(
            [version for version, _ in mac_items(feed.encode())],
            ["1.2.0", "1.1.0", "1.0.0"],
        )

    def test_sparkle_skips_deleted_previews_and_stages_only_available_archives(self):
        for available in (("1.2.0", "1.0.0"), ("1.2.0",), ()):
            with self.subTest(available=available):
                host = self.host / f"case-{len(available)}"
                host.mkdir()
                items = []
                for version in ("1.2.0", "1.1.0", "1.0.0"):
                    name = f"AI-Detector-{version}.dmg"
                    if version in available:
                        (host / name).write_bytes(version.encode())
                    items.append(
                        f'<item><sparkle:version>{version}</sparkle:version><enclosure url="{self.url}/{host.name}/{name}" /></item>'
                    )
                (host / "appcast.xml").write_text(
                    '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel>'
                    + "".join(items)
                    + "</channel></rss>"
                )
                output = self.output / host.name
                prepare(output, "macos-arm64", "1.3.0", f"{self.url}/{host.name}")
                folder = output / "macos-updates"
                self.assertEqual(
                    {path.name for path in folder.glob("*.dmg")},
                    {f"AI-Detector-{version}.dmg" for version in available},
                )
                self.assertEqual(
                    tuple(
                        version
                        for version, _ in mac_items(
                            (folder / "appcast.xml").read_bytes()
                        )
                    ),
                    available,
                )
