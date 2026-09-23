import hashlib
import json
import os
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from fixtures.keys import PUBLIC_KEY
from package import PackageInputs, assemble_package
from package import archive as archive_package


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
        self.mac_detector = self.root / "aidetector.app"
        (self.mac_detector / "Contents/MacOS").mkdir(parents=True)
        (self.mac_detector / "Contents/MacOS/aidetector").write_bytes(b"detector")
        (self.mac_detector / "Contents/MacOS/aidetector").chmod(0o755)
        (self.mac_detector / "Contents/Resources").mkdir()
        (self.mac_detector / "Contents/Resources/library").write_bytes(
            b"runtime dependency"
        )
        self.web = self.root / "web"
        self.web.write_bytes(b"web")
        self.launcher = self.root / "launcher"
        self.launcher.write_bytes(b"native launcher")
        self.windows_launcher = self.root / "windows-launcher"
        self.windows_launcher.mkdir()
        (self.windows_launcher / "AI Detector.exe").write_bytes(b"native launcher")
        (self.windows_launcher / "AI Detector.exe.config").write_text(
            "<configuration/>"
        )
        for name in (
            "Velopack.dll",
            "Newtonsoft.Json.dll",
            "BouncyCastle.Cryptography.dll",
            "ThirdPartyNotices.txt",
        ):
            (self.windows_launcher / name).write_text(name)
        self.sparkle = self.root / "sparkle"
        (self.sparkle / "Sparkle.framework/Versions/B").mkdir(parents=True)
        (self.sparkle / "Sparkle.framework/Versions/B/Sparkle").write_bytes(
            b"framework"
        )
        (self.sparkle / "LICENSE").write_text("Sparkle license")
        self.ffmpeg = self.root / "ffmpeg"
        self.ffmpeg.write_bytes(b"ffmpeg")
        self.ffmpeg.chmod(0o755)

    def test_complete_download_and_checksum(self):
        for platform, launcher, encoder in (
            ("windows-x64", "ai-detector-web.exe", "ffmpeg.exe"),
            ("macos-arm64", "ai-detector-web", "ffmpeg"),
            ("linux-x64", "AI Detector", "ffmpeg"),
        ):
            if platform == "macos-arm64" and os.name == "nt":
                continue  # Unprivileged Windows runners cannot create bundle symlinks.
            with self.subTest(platform=platform):
                folder = assemble_package(
                    PackageInputs(
                        self.mac_detector
                        if platform == "macos-arm64"
                        else self.detector,
                        self.web,
                        self.ffmpeg,
                        self.root / "out",
                        platform,
                        "image@sha256:123",
                        version="app/v1.2.3",
                        mac_launcher=self.launcher
                        if platform == "macos-arm64"
                        else None,
                        sparkle=self.sparkle if platform == "macos-arm64" else None,
                        windows_launcher=self.windows_launcher
                        if platform == "windows-x64"
                        else None,
                    )
                )
                self.assertFalse(folder.with_suffix(".zip").exists())
                archive = archive_package(folder)
                with zipfile.ZipFile(archive) as download:
                    base = f"AI-Detector-{platform}/"
                    prefix = (
                        base + "AI Detector.app/Contents/MacOS/"
                        if platform == "macos-arm64"
                        else base
                    )
                    if platform == "macos-arm64":
                        detector = (
                            base
                            + "AI Detector.app/Contents/Helpers/Detector.app/Contents/"
                        )
                        self.assertEqual(
                            download.read(prefix + "detector"),
                            b"../Helpers/Detector.app/Contents/MacOS",
                        )
                        self.assertEqual(
                            download.read(detector + "MacOS/aidetector"), b"detector"
                        )
                        self.assertEqual(
                            download.read(detector + "Resources/library"),
                            b"runtime dependency",
                        )
                    else:
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
                            download.read(prefix + "AI Detector.exe"),
                            b"native launcher",
                        )
                        self.assertIn(
                            prefix + "AI Detector.exe.config",
                            download.namelist(),
                        )
                        self.assertIn(prefix + "Lucide.LICENSE", download.namelist())
                        for name in (
                            "Velopack.dll",
                            "Newtonsoft.Json.dll",
                            "ThirdPartyNotices.txt",
                        ):
                            self.assertEqual(
                                download.read(prefix + name).decode(), name
                            )
                    self.assertEqual(
                        download.read(prefix + "bin/" + encoder), b"ffmpeg"
                    )
                    metadata = prefix + "application.json"
                    if platform == "macos-arm64":
                        self.assertEqual(
                            download.read(metadata), b"../Resources/application.json"
                        )
                        metadata = (
                            base + "AI Detector.app/Contents/Resources/application.json"
                        )
                    self.assertEqual(
                        json.loads(download.read(metadata)),
                        {"dockerImage": "image@sha256:123"},
                    )
                    if os.name != "nt":
                        for executable in (
                            launcher,
                            "detector"
                            if platform == "macos-arm64"
                            else "detector/aidetector",
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
        folder = assemble_package(
            PackageInputs(
                self.detector,
                self.web,
                self.ffmpeg,
                self.root / "out",
                "linux-x64",
                None,
            )
        )
        archive = archive_package(folder)
        with zipfile.ZipFile(archive) as download:
            self.assertEqual(
                json.loads(download.read("AI-Detector-linux-x64/application.json")), {}
            )

    def test_installed_updates_pin_the_public_key_on_both_platforms(self):
        for platform in ("macos-arm64", "windows-x64"):
            if platform == "macos-arm64" and os.name == "nt":
                continue
            with self.subTest(platform=platform):
                folder = assemble_package(
                    PackageInputs(
                        self.mac_detector
                        if platform == "macos-arm64"
                        else self.detector,
                        self.web,
                        self.ffmpeg,
                        self.root / "release",
                        platform,
                        None,
                        mac_launcher=self.launcher,
                        windows_launcher=self.windows_launcher,
                        sparkle=self.sparkle,
                        update_feed="https://example.test/updates",
                        sparkle_public_key=PUBLIC_KEY,
                    )
                )
                archive = archive_package(folder)
                with zipfile.ZipFile(archive) as packed:
                    if platform == "macos-arm64":
                        info = plistlib.loads(
                            packed.read(
                                f"AI-Detector-{platform}/AI Detector.app/Contents/Info.plist"
                            )
                        )
                        self.assertEqual(info["SUPublicEDKey"], PUBLIC_KEY)
                        self.assertTrue(info["SUVerifyUpdateBeforeExtraction"])
                        self.assertTrue(info["SURequireSignedFeed"])
                        self.assertEqual(
                            info["SUSignedFeedFailureExpirationInterval"], 0
                        )
                    else:
                        info = json.loads(
                            packed.read(f"AI-Detector-{platform}/application.json")
                        )
                        self.assertEqual(info["updatePublicKey"], PUBLIC_KEY)
                        self.assertIn(
                            f"AI-Detector-{platform}/BouncyCastle.Cryptography.dll",
                            packed.namelist(),
                        )

    def test_windows_requires_its_launcher_before_creating_a_package(self):
        output = self.root / "out"
        with self.assertRaisesRegex(ValueError, "compiled native launcher"):
            assemble_package(
                PackageInputs(
                    self.detector, self.web, self.ffmpeg, output, "windows-x64", None
                )
            )
        self.assertFalse(output.exists())

    def test_macos_rejects_the_unbundled_python_runtime(self):
        output = self.root / "out"
        with self.assertRaisesRegex(ValueError, "PyInstaller's aidetector.app"):
            assemble_package(
                PackageInputs(
                    self.detector,
                    self.web,
                    self.ffmpeg,
                    output,
                    "macos-arm64",
                    None,
                    mac_launcher=self.launcher,
                    sparkle=self.sparkle,
                )
            )
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
        folder = assemble_package(PackageInputs(*arguments))
        self.assertFalse(folder.with_suffix(".zip").exists())
        archive = archive_package(folder)
        original = archive.read_bytes()
        self.web.write_bytes(b"new web binary")

        with self.assertRaises(FileExistsError):
            assemble_package(PackageInputs(*arguments))

        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual((archive.with_suffix("") / "AI Detector").read_bytes(), b"web")
