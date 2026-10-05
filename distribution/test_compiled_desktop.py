"""Exercise the shipped web executable against a small compiled detector fixture."""

import http.cookiejar
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from build import ROOT, TARGETS, native_platform, warm_windows_compiler
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
        if native_platform() == "windows-x64":
            # These tests may run without a web build before them in the same job.
            warm_windows_compiler()
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

    def launch(self, open_browser=False, host="127.0.0.1", **fixture_options):
        (self.data / "config.json").write_text(
            json.dumps(
                {
                    "detectors": [{"detection": {"source": "input.bmp"}}],
                    "runtime": "native",
                }
            )
        )
        (self.data / "fixture-options.json").write_text(json.dumps(fixture_options))
        (self.data / "app.json").write_text(json.dumps({"monitoring": True}))
        log = self.log.open("w")
        self.addCleanup(log.close)
        env = {
            **os.environ,
            "AIDETECTOR_DATA_DIR": str(self.data),
            "AIDETECTOR_EXECUTABLE": str(self.detector),
            "AIDETECTOR_DESKTOP_HOST": "1",
            "OPEN_BROWSER": str(open_browser).lower(),
            "PORT": str(self.port),
        }
        if host is None:
            env.pop("HOST", None)
        else:
            env["HOST"] = host
        process = subprocess.Popen(
            [str(self.web)],
            env=env,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
        )
        self.addCleanup(cleanup_process, process)
        return process

    def test_default_dashboard_pairs_lan_browsers_and_respects_loopback_override(
        self,
    ):
        # UDP connect selects the local interface without sending a packet.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            try:
                route.connect(("192.0.2.1", 9))
            except OSError:
                self.skipTest("Requires a non-loopback IPv4 network route")
            address = route.getsockname()[0]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for host in (None, "127.0.0.1"):
            with self.subTest(host=host):
                process = self.launch(host=host)
                try:
                    wait_for(
                        process,
                        lambda: "AI Detector is ready at" in self.log.read_text(),
                        self.log,
                    )
                    with opener.open(
                        f"http://127.0.0.1:{self.port}/", timeout=5
                    ) as response:
                        self.assertEqual(response.status, 200)
                    url = f"http://{address}:{self.port}/"
                    if host is None:
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            opener.open(url + "logs/output", timeout=5)
                        self.assertEqual(denied.exception.code, 401)
                        # A phone fetches these without its pairing cookie, to keep
                        # the application on its home screen.
                        for name in ("manifest.webmanifest", "apple-touch-icon.png"):
                            with opener.open(url + name, timeout=5) as response:
                                self.assertEqual(response.status, 200)
                        browser = urllib.request.build_opener(
                            urllib.request.ProxyHandler({}),
                            urllib.request.HTTPCookieProcessor(
                                http.cookiejar.CookieJar()
                            ),
                        )
                        request = urllib.request.Request(
                            url, headers={"Accept": "text/html"}
                        )
                        with browser.open(request, timeout=5) as response:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.url, url + "pair")
                        pairing = re.search(
                            r"initial pairing code: (\d{6})", self.log.read_text()
                        )
                        self.assertIsNotNone(pairing, self.log.read_text())
                        request = urllib.request.Request(
                            url + "pair",
                            data=urllib.parse.urlencode(
                                {"code": pairing[1], "name": "CI browser"}
                            ).encode(),
                            headers={"Origin": url.rstrip("/"), "Accept": "text/html"},
                        )
                        with browser.open(request, timeout=5) as response:
                            self.assertEqual(response.status, 200)
                            self.assertNotEqual(response.url, url + "pair")
                            self.assertIn(b"<!doctype html>", response.read().lower())
                        with browser.open(url + "devices", timeout=5) as response:
                            self.assertIn(b"CI browser", response.read())
                        self.assertIn(
                            f"LAN URL: http://{address}:{self.port}",
                            self.log.read_text(),
                        )
                    else:
                        with self.assertRaises(urllib.error.URLError) as unreachable:
                            opener.open(url, timeout=5)
                        self.assertNotIsInstance(
                            unreachable.exception, urllib.error.HTTPError
                        )
                        self.assertNotIn("LAN URL:", self.log.read_text())
                    process.stdin.write(b"quit\n")
                    process.stdin.flush()
                    wait_for(
                        process,
                        lambda child=process: child.poll() is not None,
                        self.log,
                    )
                    self.assertEqual(process.returncode, 0, self.log.read_text())
                finally:
                    cleanup_process(process)

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
        self.assertTrue(json.loads((self.data / "app.json").read_text())["monitoring"])
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

    def test_losing_native_menu_keeps_the_real_monitoring_service_running(self):
        process = self.launch()
        wait_for(
            process,
            lambda: (
                (self.data / "starts.txt").exists()
                and "AI_DETECTOR_READY" in self.log.read_text()
            ),
            self.log,
        )
        process.stdin.close()
        wait_for(
            process,
            lambda: (
                (self.data / "logs/application.log").exists()
                and "Native launcher disconnected; monitoring continues"
                in (self.data / "logs/application.log").read_text()
            ),
            self.log,
        )
        self.assertIsNone(process.poll())
        self.assertFalse((self.data / "flushed.txt").exists())
        self.assertEqual((self.data / "starts.txt").read_text().count("started"), 1)
        with subprocess.Popen(
            [str(self.web), "--quit"],
            env={
                **os.environ,
                "AIDETECTOR_DATA_DIR": str(self.data),
                "PORT": str(self.port),
                "OPEN_BROWSER": "false",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as quitting:
            self.assertEqual(process.wait(timeout=15), 0)
            _, errors = quitting.communicate(timeout=15)
            self.assertEqual(quitting.returncode, 0, errors.decode())
        self.assertEqual((self.data / "flushed.txt").read_text(), "flushed")
