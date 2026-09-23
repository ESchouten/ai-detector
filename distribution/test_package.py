import hashlib
import json
import os
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from package import package


class PackageTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.detector = self.root / "native"
        self.detector.mkdir()
        (self.detector / "aidetector").write_bytes(b"detector")
        (self.detector / "aidetector").chmod(0o755)
        runtime = self.detector / "_internal"
        runtime.mkdir()
        (runtime / "library").write_bytes(b"runtime dependency")
        self.web = self.root / "web"
        self.web.write_bytes(b"web")
        self.launcher = self.root / "launcher"
        self.launcher.write_bytes(b"native launcher")
        self.tray = self.root / "tray"
        self.tray.mkdir()
        (self.tray / "AI Detector Tray.exe").write_bytes(b"native tray")
        (self.tray / "AI Detector Tray.exe.config").write_text("<configuration/>")
        self.ffmpeg = self.root / "ffmpeg"
        self.ffmpeg.write_bytes(b"ffmpeg")
        self.ffmpeg.chmod(0o755)

    def test_complete_download_and_checksum(self):
        for platform, launcher, encoder in (
            ("windows-x64", "AI Detector.exe", "ffmpeg.exe"),
            ("macos-arm64", "ai-detector-web", "ffmpeg"),
            ("linux-x64", "AI Detector", "ffmpeg"),
        ):
            with self.subTest(platform=platform):
                archive = package(
                    self.detector,
                    self.web,
                    self.ffmpeg,
                    self.root / "out",
                    platform,
                    "image@sha256:123",
                    version="app/v1.2.3",
                    mac_launcher=self.launcher if platform == "macos-arm64" else None,
                    windows_tray=self.tray if platform == "windows-x64" else None,
                )
                with zipfile.ZipFile(archive) as download:
                    base = f"AI-Detector-{platform}/"
                    prefix = (
                        base + "AI Detector.app/Contents/MacOS/"
                        if platform == "macos-arm64"
                        else base
                    )
                    self.assertEqual(
                        download.read(prefix + "detector/aidetector"), b"detector"
                    )
                    self.assertEqual(
                        download.read(prefix + "detector/_internal/library"),
                        b"runtime dependency",
                    )
                    self.assertEqual(download.read(prefix + launcher), b"web")
                    if platform == "windows-x64":
                        self.assertEqual(
                            download.read(prefix + "tray/AI Detector Tray.exe"),
                            b"native tray",
                        )
                        self.assertIn(
                            prefix + "tray/AI Detector Tray.exe.config",
                            download.namelist(),
                        )
                        self.assertIn(
                            prefix + "tray/Lucide.LICENSE", download.namelist()
                        )
                    self.assertEqual(
                        download.read(prefix + "bin/" + encoder), b"ffmpeg"
                    )
                    self.assertEqual(
                        json.loads(download.read(prefix + "application.json")),
                        {"dockerImage": "image@sha256:123"},
                    )
                    if os.name != "nt":
                        for executable in (
                            launcher,
                            "detector/aidetector",
                            "bin/" + encoder,
                        ):
                            self.assertTrue(
                                download.getinfo(prefix + executable).external_attr
                                >> 16
                                & 0o111
                            )
                    instructions = download.read(base + "START HERE.txt").decode(
                        "utf-8"
                    )
                    self.assertIn(
                        "Closing the browser leaves monitoring active", instructions
                    )
                    self.assertNotIn("Use Stop detection before closing", instructions)
                    if platform == "macos-arm64":
                        info = plistlib.loads(
                            download.read(base + "AI Detector.app/Contents/Info.plist")
                        )
                        self.assertEqual(info["CFBundleShortVersionString"], "1.2.3")
                        self.assertEqual(info["LSMinimumSystemVersion"], "14.0")
                        self.assertTrue(info["LSUIElement"])
                        self.assertEqual(
                            download.read(prefix + info["CFBundleExecutable"]),
                            b"native launcher",
                        )
                    self.assertNotIn(prefix + "config.json", download.namelist())
                with archive.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                self.assertEqual(
                    archive.with_suffix(".zip.sha256").read_text(encoding="utf-8"),
                    f"{digest}  {archive.name}\n",
                )

    def test_native_preview_omits_the_docker_image(self):
        archive = package(
            self.detector,
            self.web,
            self.ffmpeg,
            self.root / "out",
            "linux-x64",
            None,
        )
        with zipfile.ZipFile(archive) as download:
            self.assertEqual(
                json.loads(download.read("AI-Detector-linux-x64/application.json")), {}
            )

    def test_windows_requires_its_tray_before_creating_a_package(self):
        output = self.root / "out"
        with self.assertRaisesRegex(ValueError, "compiled native tray"):
            package(self.detector, self.web, self.ffmpeg, output, "windows-x64", None)
        self.assertFalse(output.exists())

    def test_existing_package_is_not_overwritten(self):
        arguments = (
            self.detector,
            self.web,
            self.ffmpeg,
            self.root / "out",
            "linux-x64",
            None,
        )
        archive = package(*arguments)
        original = archive.read_bytes()
        self.web.write_bytes(b"new web binary")

        with self.assertRaises(FileExistsError):
            package(*arguments)

        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual((archive.with_suffix("") / "AI Detector").read_bytes(), b"web")
