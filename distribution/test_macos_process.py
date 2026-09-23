"""Exercise the production Mac process owner without installing an application."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
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

    def launch(self, fail_shutdown=False):
        fixture = (
            Path(__file__).resolve().parent.parent
            / "web/desktop/fixtures/runtime-server.ts"
        )
        log_path = self.data / "launcher.log"
        log = log_path.open("w")
        self.addCleanup(log.close)
        process = subprocess.Popen(
            [str(self.launcher), shutil.which("bun"), str(fixture)],
            env={
                **os.environ,
                "AIDETECTOR_DATA_DIR": str(self.data),
                "PORT": str(self.port),
                "HOST": "127.0.0.1",
                "OPEN_BROWSER": "false",
                "FIXTURE_FAIL_SHUTDOWN": str(fail_shutdown).lower(),
            },
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
        )
        self.addCleanup(cleanup_process, process)
        wait_for(process, lambda: "AI_DETECTOR_READY" in log_path.read_text(), log_path)
        return process

    def quit(self, process):
        process.stdin.write(b"quit\n")
        process.stdin.flush()
        self.assertEqual(process.wait(timeout=15), 0)
        self.assertFalse((self.data / "desktop-instance.json").exists())

    def test_quit_waits_for_monitoring_to_drain(self):
        self.quit(self.launch())
        self.assertEqual((self.data / "drained").read_text(), "200")

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

    def test_crashed_parent_drains_and_reopened_owner_can_quit(self):
        process = self.launch()
        process.kill()
        process.wait(timeout=5)
        deadline = time.monotonic() + 15
        while (
            self.data / "desktop-instance.json"
        ).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse((self.data / "desktop-instance.json").exists())
        self.assertEqual((self.data / "drained").read_text(), "200")
        self.quit(self.launch())
        self.assertEqual((self.data / "starts").read_text(), "started\nstarted\n")
        self.assertEqual((self.data / "drained").read_text(), "200200")
