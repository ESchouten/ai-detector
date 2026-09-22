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

from installers import linux_tree
from package import archive, macos_bundle, version_number
from sign_macos import sign_app


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

    def test_invalid_versions_and_fake_release_identities_fail_before_signing(self):
        for value in ("main", "1.2", "1.2.3\nInjected=command", "../1.2.3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_number(value)
        for identity in ("-", "Apple Development: local", ""):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                sign_app(self.payload, identity)
