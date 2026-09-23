"""Exercise the actual desktop runtime with a small local application fixture."""

import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from fixtures.processes import cleanup_process, wait_for

FIXTURE = (
    Path(__file__).resolve().parent.parent / "web/desktop/fixtures/runtime-server.ts"
)


@unittest.skipUnless(
    shutil.which("bun"), "Bun is required for executable launcher integration"
)
class LauncherTest(unittest.TestCase):
    def test_native_shell_quit_and_lost_pipe_both_drain_monitoring(self):
        for command in (b"quit\n", None):
            with (
                self.subTest(command=command),
                tempfile.TemporaryDirectory(prefix="ai-host-") as temporary,
            ):
                folder = Path(temporary)
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    port = listener.getsockname()[1]
                env = {
                    **os.environ,
                    "AIDETECTOR_DATA_DIR": str(folder / "data"),
                    "AIDETECTOR_DESKTOP_HOST": "1",
                    "HOST": "127.0.0.1",
                    "PORT": str(port),
                    "OPEN_BROWSER": "false",
                }
                log_path = folder / "launcher.log"
                log = log_path.open("w")
                process = subprocess.Popen(
                    [shutil.which("bun"), str(FIXTURE)],
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=log,
                )
                try:
                    wait_for(
                        process,
                        lambda log_path=log_path: (
                            "AI_DETECTOR_READY" in log_path.read_text()
                        ),
                        log_path,
                    )
                    if command:
                        process.stdin.write(command)
                        process.stdin.flush()
                    else:
                        process.stdin.close()
                    process.wait(timeout=10)
                    self.assertEqual(process.returncode, 0, log_path.read_text())
                    self.assertEqual((folder / "data/drained").read_text(), "200")
                finally:
                    cleanup_process(process)
                    log.close()

    def test_second_launch_does_not_initialize_another_server_and_quit_is_graceful(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="ai-launcher-") as temporary:
            folder = Path(temporary)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            env = {
                **os.environ,
                "AIDETECTOR_DATA_DIR": str(folder / "data"),
                "HOST": "127.0.0.1",
                "PORT": str(port),
                "OPEN_BROWSER": "false",
            }
            arguments = [shutil.which("bun"), str(FIXTURE)]
            with (folder / "log").open("w+") as log:
                process = subprocess.Popen(arguments, env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 15
                    starts = folder / "data/starts"
                    while (
                        not starts.exists()
                        and process.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.05)
                    self.assertTrue(
                        starts.exists(),
                        "Startup must initialize without a browser request",
                    )
                    second = subprocess.run(
                        [*arguments, "--background"],
                        env=env,
                        capture_output=True,
                        timeout=15,
                    )
                    self.assertEqual(second.returncode, 0, second.stderr.decode())
                    self.assertEqual(starts.read_text(), "started\n")
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=2
                    ) as response:
                        self.assertEqual(response.read(), b"fixture dashboard")
                    with subprocess.Popen(
                        [*arguments, "--quit"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    ) as quitting:
                        # Reap the owner while the helper waits; a POSIX zombie still has a PID.
                        process.wait(timeout=15)
                        _, errors = quitting.communicate(timeout=15)
                        self.assertEqual(quitting.returncode, 0, errors.decode())
                    self.assertEqual((folder / "data/drained").read_text(), "200")
                    self.assertFalse((folder / "data/desktop-instance.json").exists())
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                    log.seek(0)
                    print(log.read())
