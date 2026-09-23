"""Exercise the shipped web executable against a small compiled detector fixture."""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

from build import ROOT, TARGETS, native_platform
from fixtures.processes import cleanup_process, wait_for


@unittest.skipUnless(
    os.environ.get("DESKTOP_WEB_EXECUTABLE"),
    "Set DESKTOP_WEB_EXECUTABLE to the compiled web application",
)
class CompiledDesktopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = Path(os.environ["DESKTOP_WEB_EXECUTABLE"]).resolve(strict=True)
        temporary = tempfile.TemporaryDirectory(prefix="ai-compiled-detector-")
        cls.addClassCleanup(temporary.cleanup)
        target = TARGETS[native_platform()]
        cls.detector = Path(temporary.name) / f"detector{target.suffix}"
        subprocess.run(
            [
                shutil.which("bun"),
                "build",
                "--compile",
                f"--target=bun-{target.bun}",
                str(ROOT / "web/tests/fixtures/detector.mjs"),
                "--outfile",
                str(cls.detector),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ai-compiled-data-")
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.log = self.data / "desktop.log"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]

    def launch(self, open_browser=False, **fixture_options):
        (self.data / "config.json").write_text(
            json.dumps(
                {
                    "detectors": [{"detection": {"source": "input.bmp"}}],
                    **fixture_options,
                }
            )
        )
        (self.data / "runtime.json").write_text(
            json.dumps({"enabled": True, "mode": "native"})
        )
        log = self.log.open("w")
        self.addCleanup(log.close)
        process = subprocess.Popen(
            [str(self.web)],
            env={
                **os.environ,
                "AIDETECTOR_DATA_DIR": str(self.data),
                "AIDETECTOR_EXECUTABLE": str(self.detector),
                "AIDETECTOR_DESKTOP_HOST": "1",
                "OPEN_BROWSER": str(open_browser).lower(),
                "HOST": "127.0.0.1",
                "PORT": str(self.port),
            },
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
        )
        self.addCleanup(cleanup_process, process)
        return process

    def check_shutdown(self, expected, **fixture_options):
        process = self.launch(**fixture_options)
        wait_for(
            process,
            lambda: (
                (self.data / "starts.txt").exists()
                and "AI_DETECTOR_READY" in self.log.read_text()
            ),
            self.log,
        )
        process.stdin.write(b"quit\n")
        process.stdin.flush()
        self.assertEqual(process.wait(timeout=45), expected, self.log.read_text())
        self.assertFalse((self.data / "desktop-instance.json").exists())
        self.assertTrue(json.loads((self.data / "runtime.json").read_text())["enabled"])
        messages = [
            line
            for line in self.log.read_text().splitlines()
            if line.startswith("AI_DETECTOR_ERROR ")
        ]
        self.assertEqual(len(messages), 0 if expected == 0 else 1)
        return self.log.read_text()

    def test_successful_detector_drain_exits_successfully(self):
        self.check_shutdown(0)
        self.assertEqual((self.data / "flushed.txt").read_text(), "flushed")

    def test_failed_detector_drain_exits_unsuccessfully(self):
        self.assertIn("stopped unexpectedly", self.check_shutdown(1, stopExitCode=17))

    def test_hung_detector_is_reaped_and_forced_shutdown_is_a_failure(self):
        self.assertIn("forced to stop", self.check_shutdown(1, ignoreStop=True))
        self.assertFalse((self.data / "flushed.txt").exists())

    def test_port_conflict_reports_one_actionable_error_without_readiness(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            self.port = occupied.getsockname()[1]
            # Startup fails before browser opening. The native-host flag alone
            # must suppress the web runtime's standalone Windows error dialog.
            process = self.launch(open_browser=True)
            self.assertNotEqual(process.wait(timeout=15), 0)
        log = self.log.read_text()
        self.assertNotIn("AI_DETECTOR_READY", log)
        messages = [
            line for line in log.splitlines() if line.startswith("AI_DETECTOR_ERROR ")
        ]
        self.assertEqual(len(messages), 1)
        self.assertIn(f"port {self.port}", messages[0])
