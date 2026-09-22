import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from package import package


class PackageTest(unittest.TestCase):
    def test_complete_download_and_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detector = root / "native"
            detector.mkdir()
            (detector / "aidetector").write_bytes(b"detector")
            web = root / "web"
            web.write_bytes(b"web")
            ffmpeg = root / "ffmpeg"
            ffmpeg.write_bytes(b"ffmpeg")
            archive = package(detector, web, ffmpeg, root / "out", "macos-arm64", "image@sha256:123")
            with zipfile.ZipFile(archive) as download:
                prefix = "AI-Detector-macos-arm64/"
                self.assertEqual(download.read(prefix + "detector/aidetector"), b"detector")
                self.assertEqual(download.read(prefix + "bin/ffmpeg"), b"ffmpeg")
                self.assertEqual(json.loads(download.read(prefix + "application.json")), {"dockerImage": "image@sha256:123"})
                self.assertTrue(download.getinfo(prefix + "AI Detector.command").external_attr >> 16 & 0o111)
                self.assertNotIn(prefix + "config.json", download.namelist())
            with archive.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            self.assertEqual(archive.with_suffix(".zip.sha256").read_text(), f"{digest}  {archive.name}\n")
