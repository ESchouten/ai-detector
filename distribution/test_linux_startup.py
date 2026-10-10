import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from linux_startup import (
    desktop_argument,
    install,
    open_browser,
    startup_paths,
    uninstall,
    wait_for_webapp,
)


@contextmanager
def webapp(*, ready_after=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if len(requests) <= ready_after:
                self.send_response(503)
            elif self.path == "/":
                self.send_response(302)
                self.send_header("Location", "/detections")
            else:
                self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/", requests
        finally:
            server.shutdown()
            thread.join()


@unittest.skipIf(
    sys.platform == "win32", "Linux installer uses POSIX command executables"
)
class LinuxStartupTest(unittest.TestCase):
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        temporary = self.contexts.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(temporary) / 'Farm computer $ ` " % \\ café'
        self.root.mkdir()
        self.compose = self.root / "compose.yml"
        self.compose.write_text("services: {}\n")
        self.log = self.root / "commands.jsonl"
        self.configuration = self.root / "configuration.json"
        self.configuration.write_text(
            json.dumps(
                {
                    "services": {
                        "aidetector": {"restart": "unless-stopped"},
                        "web": {"restart": "unless-stopped"},
                    }
                }
            )
        )
        commands = self.root / "bin"
        commands.mkdir()
        for command in ("sudo", "systemctl", "docker", "xdg-open"):
            executable = commands / command
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "name = Path(sys.argv[0]).name\n"
                "with open(os.environ['STARTUP_TEST_LOG'], 'a') as log:\n"
                "    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
                "if name == 'sudo':\n"
                "    os.execvp(sys.argv[1], sys.argv[1:])\n"
                "if name == 'docker' and 'config' in sys.argv:\n"
                "    print(Path(os.environ['STARTUP_TEST_CONFIG']).read_text())\n"
                "if name == 'docker' and 'up' in sys.argv and os.environ.get('STARTUP_TEST_FAIL'):\n"
                "    sys.exit(1)\n"
            )
            executable.chmod(0o755)
        self.contexts.enter_context(
            patch.dict(
                os.environ,
                {
                    "PATH": str(commands) + os.pathsep + os.environ.get("PATH", ""),
                    "XDG_CONFIG_HOME": str(self.root / "config"),
                    "XDG_DATA_HOME": str(self.root / "data"),
                    "STARTUP_TEST_LOG": str(self.log),
                    "STARTUP_TEST_CONFIG": str(self.configuration),
                },
            )
        )

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_installs_one_launcher_and_preserves_data_on_removal(self):
        install(self.compose, "http://localhost:8080/")
        desktop, launcher = startup_paths()
        self.assertIn("http://localhost:8080/", desktop.read_text())
        self.assertIn("Terminal=false", desktop.read_text())
        self.assertEqual(
            launcher.read_bytes(),
            Path(__file__).with_name("linux_startup.py").read_bytes(),
        )
        self.assertIn(
            ["systemctl", "enable", "--now", "docker.service"], self.commands()
        )
        self.assertIn(
            ["docker", "compose", "-f", str(self.compose.resolve()), "up", "-d"],
            self.commands(),
        )

        original = desktop.read_text()
        install(self.compose, "http://localhost:8080/")
        self.assertEqual(desktop.read_text(), original)
        recording = launcher.parent / "recording.mp4"
        recording.write_bytes(b"recording")
        uninstall()
        uninstall()
        self.assertFalse(desktop.exists())
        self.assertFalse(launcher.exists())
        self.assertEqual(recording.read_bytes(), b"recording")
        self.assertTrue(self.compose.exists())

    def test_does_not_install_autostart_when_containers_fail_to_start(self):
        with patch.dict(os.environ, {"STARTUP_TEST_FAIL": "1"}):
            with self.assertRaises(subprocess.CalledProcessError):
                install(self.compose, "http://localhost/")
        self.assertFalse(startup_paths()[0].exists())

    def test_rejects_services_without_reboot_policy_before_enabling_docker(self):
        self.configuration.write_text(json.dumps({"services": {"web": {}}}))
        with self.assertRaisesRegex(ValueError, "restart: unless-stopped"):
            install(self.compose, "http://localhost/")
        self.assertFalse(any(command[0] == "systemctl" for command in self.commands()))
        self.assertFalse(startup_paths()[0].exists())

    def test_opens_browser_once_after_webapp_is_ready_and_follows_home_redirect(self):
        with webapp(ready_after=1) as (url, requests):
            open_browser(url)
        self.assertEqual(requests, ["/", "/", "/detections"])
        self.assertEqual(self.commands(), [["xdg-open", url]])

    def test_readiness_has_a_deadline(self):
        with webapp(ready_after=100) as (url, requests):
            with self.assertRaisesRegex(TimeoutError, "did not respond"):
                wait_for_webapp(url, timeout=0.05)
        self.assertEqual(requests, ["/"])
        self.assertFalse(self.log.exists())

    @unittest.skipUnless(
        sys.platform == "linux" and shutil.which("gio"),
        "Desktop Entry launch requires Linux GIO",
    )
    def test_desktop_launch_handles_spaces_and_special_characters(self):
        with webapp() as (url, requests):
            install(self.compose, url)
            desktop, _ = startup_paths()
            subprocess.run(["desktop-file-validate", str(desktop)], check=True)
            subprocess.run(["gio", "launch", str(desktop)], check=True)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if ["xdg-open", url] in self.commands():
                    break
                time.sleep(0.05)
            self.assertIn(["xdg-open", url], self.commands())
        self.assertEqual(requests, ["/", "/detections"])


class DesktopArgumentTest(unittest.TestCase):
    def test_quotes_spaces_and_escapes_desktop_field_codes(self):
        self.assertEqual(desktop_argument("Farm files/100%"), '"Farm files/100%%"')

    def test_escapes_exec_metacharacters_and_then_desktop_string(self):
        self.assertEqual(
            desktop_argument('$HOME/"camera"'), '"\\\\$HOME/\\\\"camera\\\\""'
        )
        self.assertEqual(desktop_argument("a\\b"), '"a\\\\\\\\b"')
