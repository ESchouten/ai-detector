"""Exercise the production Mac process owner without installing an application."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from fixtures.processes import cleanup_process, wait_for


@unittest.skipUnless(
    sys.platform == "darwin" and shutil.which("bun"), "Requires macOS and Bun"
)
class MacProcessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-mac-process-")
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        cls.launcher = root / "process-fixture"
        source = Path(__file__).parent / "macos"
        subprocess.run(
            [
                "xcrun",
                "swiftc",
                "-parse-as-library",
                "-module-cache-path",
                str(root / "module-cache"),
                str(source / "DesktopProcess.swift"),
                str(source / "ProcessFixture.swift"),
                "-o",
                str(cls.launcher),
            ],
            check=True,
            timeout=60,
        )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ai-mac-data-")
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.addCleanup(self.stop_background)

    def launch(self, fail_shutdown=False):
        fixture = (
            Path(__file__).resolve().parent.parent
            / "web/desktop/fixtures/runtime-server.ts"
        )
        log_path = self.data / "launcher.log"
        log = log_path.open("w")
        self.addCleanup(log.close)
        self.environment = {
            **os.environ,
            "AIDETECTOR_DATA_DIR": str(self.data),
            "PORT": str(self.port),
            "HOST": "127.0.0.1",
            "OPEN_BROWSER": "false",
            "FIXTURE_FAIL_SHUTDOWN": str(fail_shutdown).lower(),
        }
        process = subprocess.Popen(
            [str(self.launcher), shutil.which("bun"), str(fixture)],
            env=self.environment,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
        )
        self.addCleanup(cleanup_process, process)
        wait_for(process, lambda: "AI_DETECTOR_READY" in log_path.read_text(), log_path)
        return process

    def stop_background(self):
        if not (self.data / "desktop-instance.json").exists():
            return
        subprocess.run(
            [
                shutil.which("bun"),
                str(
                    Path(__file__).resolve().parent.parent
                    / "web/desktop/fixtures/runtime-server.ts"
                ),
                "--quit",
            ],
            env=self.environment,
            capture_output=True,
            timeout=50,
            check=True,
        )

    def quit(self, process):
        process.stdin.write(b"quit\n")
        process.stdin.flush()
        self.assertEqual(process.wait(timeout=15), 0)
        self.assertFalse((self.data / "desktop-instance.json").exists())

    def test_quit_waits_for_monitoring_to_drain(self):
        self.quit(self.launch())
        self.assertEqual((self.data / "drained").read_text(), "200")
        self.assertEqual(
            (self.data / "shutdown-reasons").read_text().strip(),
            "Native launcher sent an explicit quit command",
        )

    def test_failed_shutdown_returns_the_actionable_error_to_the_native_owner(self):
        process = self.launch(fail_shutdown=True)
        process.stdin.write(b"quit\n")
        process.stdin.flush()
        self.assertEqual(process.wait(timeout=15), 1)
        messages = [
            line
            for line in (self.data / "launcher.log").read_text().splitlines()
            if line.startswith("NATIVE_ERROR ")
        ]
        self.assertEqual(
            messages,
            [
                "NATIVE_ERROR AI Detector could not finish shutting down. The test detector could not finish."
            ],
        )

    def test_crashed_parent_keeps_monitoring_and_reopened_menu_can_quit(self):
        process = self.launch()
        identity = (self.data / "desktop-instance.json").read_text()
        process.kill()
        process.wait(timeout=5)
        deadline = time.monotonic() + 10
        while (
            not (self.data / "launcher-disconnected").exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        self.assertTrue((self.data / "launcher-disconnected").exists())
        self.assertEqual((self.data / "desktop-instance.json").read_text(), identity)
        self.assertFalse((self.data / "drained").exists())
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/", timeout=2
        ) as response:
            self.assertEqual(response.read(), b"fixture dashboard")
        replacement = self.launch()
        self.assertEqual((self.data / "desktop-instance.json").read_text(), identity)
        self.assertEqual((self.data / "starts").read_text(), "started\n")
        self.quit(replacement)
        self.assertEqual((self.data / "drained").read_text(), "200")
        self.assertEqual(
            (self.data / "shutdown-reasons").read_text().strip(),
            "Authenticated desktop quit request",
        )

    def test_web_crashes_and_unexpected_clean_exit_restart_without_losing_the_menu(
        self,
    ):
        process = self.launch()
        for count, exit_signal in enumerate((signal.SIGKILL, signal.SIGUSR2), start=2):
            with self.subTest(exit_signal=exit_signal):
                pid = int((self.data / "web-pid").read_text())
                os.kill(pid, exit_signal)
                wait_for(
                    process,
                    lambda count=count: (
                        (self.data / "starts").read_text().count("started\n") == count
                    ),
                    self.data / "launcher.log",
                )
                self.assertNotEqual(int((self.data / "web-pid").read_text()), pid)
                self.assertFalse((self.data / "drained").exists())
        self.quit(process)
        self.assertEqual((self.data / "drained").read_text(), "200")

    def test_quit_during_web_restart_delay_cancels_the_restart(self):
        process = self.launch()
        pid = int((self.data / "web-pid").read_text())
        os.kill(pid, signal.SIGKILL)
        wait_for(
            process,
            lambda: (
                "restarting in 2 seconds" in (self.data / "launcher.log").read_text()
            ),
            self.data / "launcher.log",
        )
        process.stdin.write(b"quit\n")
        process.stdin.flush()
        self.assertEqual(process.wait(timeout=5), 0)
        time.sleep(2.2)
        self.assertEqual((self.data / "starts").read_text(), "started\n")

    def test_reopened_menu_reports_a_failed_shutdown(self):
        process = self.launch(fail_shutdown=True)
        process.kill()
        process.wait(timeout=5)
        replacement = self.launch(fail_shutdown=True)
        replacement.stdin.write(b"quit\n")
        replacement.stdin.flush()
        self.assertEqual(replacement.wait(timeout=15), 1)
        self.assertIn(
            "NATIVE_ERROR AI Detector could not finish shutting down",
            (self.data / "launcher.log").read_text(),
        )
        self.assertFalse((self.data / "desktop-instance.json").exists())

    def test_authenticated_quit_does_not_trigger_native_recovery(self):
        process = self.launch()
        self.stop_background()
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertEqual((self.data / "starts").read_text(), "started\n")
        self.assertEqual((self.data / "drained").read_text(), "200")

    def test_reattached_menu_recovers_when_the_original_web_owner_crashes(self):
        original = self.launch()
        original.kill()
        original.wait(timeout=5)
        replacement = self.launch()
        pid = int((self.data / "web-pid").read_text())
        os.kill(pid, signal.SIGKILL)
        wait_for(
            replacement,
            lambda: (self.data / "starts").read_text().count("started\n") == 2,
            self.data / "launcher.log",
        )
        self.assertNotEqual(int((self.data / "web-pid").read_text()), pid)
        self.quit(replacement)

    def test_terminated_web_process_resumes_under_its_native_owner(self):
        process = self.launch()
        pid = int((self.data / "web-pid").read_text())
        os.kill(pid, signal.SIGTERM)
        wait_for(
            process,
            lambda: (self.data / "starts").read_text().count("started\n") == 2,
            self.data / "launcher.log",
        )
        self.assertNotEqual(int((self.data / "web-pid").read_text()), pid)
        self.quit(process)
        self.assertEqual((self.data / "drained").read_text(), "200200")
