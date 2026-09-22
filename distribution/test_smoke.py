import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from smoke import wait_for_detection, wait_for_setup


@contextmanager
def running_application():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        yield process
    finally:
        process.terminate()
        process.wait(timeout=5)


class SmokeTest(unittest.TestCase):
    def test_waits_for_setup_after_a_temporary_http_failure(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(503 if len(requests) == 1 else 200)
                self.end_headers()
                self.wfile.write(b"Your detector")

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with running_application() as process:
                    wait_for_setup(
                        process,
                        f"http://127.0.0.1:{server.server_port}/setup",
                        time.monotonic() + 5,
                    )
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(requests, ["/setup", "/setup"])

    def test_exited_application_fails_both_waits_without_waiting_for_timeout(self):
        with subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"]) as process:
            process.wait(timeout=5)
            with tempfile.TemporaryDirectory() as temporary:
                for wait, target in (
                    (wait_for_setup, "http://127.0.0.1:1/setup"),
                    (wait_for_detection, Path(temporary)),
                ):
                    with self.subTest(wait=wait.__name__):
                        with self.assertRaisesRegex(RuntimeError, r"status 7\)"):
                            wait(process, target, time.monotonic() + 0.1)

    def test_archive_requires_one_detection_and_nonempty_image(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            running_application() as process,
        ):
            data = Path(temporary)
            event = data / "detections/unclassified/unvalidated/event"
            event.mkdir(parents=True)
            metadata = event / "metadata.json"
            metadata.write_text(json.dumps({"detections": 1}), encoding="utf-8")
            image = event / "best.jpg"
            image.write_bytes(b"encoded image")

            wait_for_detection(process, data, time.monotonic() + 1)

            image.write_bytes(b"")
            with self.assertRaises(AssertionError):
                wait_for_detection(process, data, time.monotonic() + 1)
            image.write_bytes(b"encoded image")
            metadata.write_text(json.dumps({"detections": 2}), encoding="utf-8")
            with self.assertRaises(AssertionError):
                wait_for_detection(process, data, time.monotonic() + 1)

    def test_detection_wait_has_a_deadline_while_application_is_alive(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            running_application() as process,
        ):
            with self.assertRaisesRegex(TimeoutError, "did not create a detection"):
                wait_for_detection(process, Path(temporary), time.monotonic() + 0.05)
            self.assertIsNone(process.poll())
