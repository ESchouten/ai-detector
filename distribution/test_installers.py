import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from installers import linux_tree, macos
from package import archive, macos_bundle, version_number


class InstallerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.payload = self.root / "application"
        self.payload.mkdir()
        (self.payload / "AI Detector").write_bytes(b"application")
        (self.payload / "AI Detector").chmod(0o755)

    def test_linux_payload_has_normal_menu_login_and_uninstall_integration(self):
        root = linux_tree(self.payload, "1.2.3")
        self.assertEqual(
            (root / "opt/ai-detector/AI Detector").read_bytes(), b"application"
        )
        menu = root / "usr/share/applications/ai-detector.desktop"
        login = root / "etc/xdg/autostart/ai-detector.desktop"
        self.assertEqual(menu.read_bytes(), login.read_bytes())
        self.assertIn('Exec="/opt/ai-detector/AI Detector"', menu.read_text())
        self.assertIn("Terminal=false", menu.read_text())
        self.assertIn(
            "/etc/xdg/autostart/ai-detector.desktop",
            (root / "DEBIAN/conffiles").read_text(),
        )
        self.assertIn("Architecture: amd64", (root / "DEBIAN/control").read_text())
        self.assertIn("Version: 1.2.3", (root / "DEBIAN/control").read_text())
        self.assertTrue((root / "DEBIAN/prerm").stat().st_mode & stat.S_IXUSR)
        self.assertFalse((root / "home").exists())
        if shutil.which("desktop-file-validate"):
            subprocess.run(["desktop-file-validate", str(menu)], check=True)
        if shutil.which("dpkg-deb"):
            artifact = self.root / "test.deb"
            subprocess.run(
                ["dpkg-deb", "--root-owner-group", "--build", str(root), str(artifact)],
                check=True,
                capture_output=True,
            )
            listing = subprocess.check_output(
                ["dpkg-deb", "--contents", str(artifact)], text=True
            )
            self.assertIn("./opt/ai-detector/AI Detector", listing)
            self.assertIn("root/root", listing)

    @unittest.skipIf(os.name == "nt", "Linux package lifecycle uses a POSIX shell")
    def test_linux_removal_signals_the_installed_process_and_waits_for_exit(self):
        commands = self.root / "commands"
        commands.mkdir()
        state = self.root / "running"
        log = self.root / "calls.jsonl"
        fuser = commands / "fuser"
        fuser.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "state = Path(os.environ['TEST_FUSER_STATE'])\n"
            "with open(os.environ['TEST_FUSER_LOG'], 'a') as log: log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if '-k' in sys.argv and '-TERM' in sys.argv: state.unlink(missing_ok=True); sys.exit(0)\n"
            "sys.exit(0 if state.exists() else 1)\n"
        )
        fuser.chmod(0o755)
        for action in ("remove", "upgrade"):
            with self.subTest(action=action):
                state.touch()
                subprocess.run(
                    ["sh", str(Path(__file__).parent / "linux/prerm"), action],
                    env={
                        **os.environ,
                        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                        "TEST_FUSER_STATE": str(state),
                        "TEST_FUSER_LOG": str(log),
                    },
                    check=True,
                    timeout=5,
                )
                self.assertFalse(state.exists())
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(
            calls.count(["-k", "-TERM", "/opt/ai-detector/AI Detector"]), 2
        )

    @unittest.skipIf(os.name == "nt", "macOS bundles require symlinks")
    def test_macos_layout_targets_a_real_application_executable(self):
        launcher = self.root / "launcher"
        launcher.write_bytes(b"native menu bar executable")
        binary = macos_bundle(self.payload, launcher, "app/v2.3.4-rc.1")
        info = plistlib.loads((binary.parent / "Info.plist").read_bytes())
        self.assertEqual(info["CFBundleIdentifier"], "io.github.eschouten.ai-detector")
        self.assertEqual(info["CFBundleVersion"], "2.3.4")
        self.assertEqual(
            (binary / info["CFBundleExecutable"]).read_bytes(), launcher.read_bytes()
        )
        self.assertEqual(info["CFBundlePackageType"], "APPL")
        icon = binary.parent / "Resources" / info["CFBundleIconFile"]
        self.assertEqual(icon.read_bytes()[:4], b"icns")

    @unittest.skipUnless(sys.platform == "darwin", "Disk images require macOS")
    def test_macos_image_opens_as_a_visual_drag_and_drop_installer(self):
        from ds_store import DSStore

        binary = macos_bundle(self.payload, self.payload / "AI Detector", "1.2.3")
        (binary / "current").symlink_to("AI Detector")
        image = macos(self.payload, "1.2.3")
        subprocess.run(
            ["hdiutil", "verify", str(image)], check=True, capture_output=True
        )
        mounted = self.root / "mounted"
        subprocess.run(
            [
                "hdiutil",
                "attach",
                "-readonly",
                "-nobrowse",
                "-mountpoint",
                str(mounted),
                str(image),
            ],
            check=True,
            capture_output=True,
        )
        try:
            visible = {p.name for p in mounted.iterdir() if not p.name.startswith(".")}
            self.assertEqual(visible, {"AI Detector.app", "Applications"})
            self.assertEqual(os.readlink(mounted / "Applications"), "/Applications")
            self.assertEqual(
                os.readlink(mounted / "AI Detector.app/Contents/MacOS/current"),
                "AI Detector",
            )
            self.assertTrue((mounted / ".background.tiff").is_file())
            with DSStore.open(str(mounted / ".DS_Store"), "r") as settings:
                app_x, app_y = settings["AI Detector.app"]["Iloc"]
                folder_x, folder_y = settings["Applications"]["Iloc"]
                self.assertLess(app_x, folder_x)
                self.assertEqual(app_y, folder_y)
                self.assertEqual(settings["."]["icvp"]["backgroundType"], 2)
                self.assertFalse(settings["."]["bwsp"]["ShowToolbar"])
                self.assertFalse(settings["."]["bwsp"]["ShowSidebar"])
        finally:
            subprocess.run(
                ["hdiutil", "detach", str(mounted)], check=True, capture_output=True
            )

    @unittest.skipIf(
        os.name == "nt", "Unprivileged Windows fixtures cannot create symlinks"
    )
    def test_portable_archive_preserves_framework_symlinks(self):
        import zipfile

        (self.payload / "Current").symlink_to("Versions/A")
        artifact = archive(self.payload)
        with zipfile.ZipFile(artifact) as packed:
            info = packed.getinfo("application/Current")
            self.assertTrue(stat.S_ISLNK(info.external_attr >> 16))
            self.assertEqual(packed.read(info), b"Versions/A")

    def test_invalid_versions_fail_before_packaging(self):
        for value in (
            "main",
            "1.2",
            "1.2.3\nInjected=command",
            "../1.2.3",
            "01.2.3",
            "1.2.3-alpha_beta",
            "1.2.3-01",
            "1.2.3-alpha..1",
            "app/vv1.2.3",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_number(value)

    def test_semantic_versions_map_to_numeric_installer_versions(self):
        for value in (
            "1.2.3",
            "v1.2.3",
            "app/v1.2.3",
            "1.2.3-rc.1+build.2",
            "app/v1.2.3+build.02",
        ):
            with self.subTest(value=value):
                self.assertEqual(version_number(value), "1.2.3")
