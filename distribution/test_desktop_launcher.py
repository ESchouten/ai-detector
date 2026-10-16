"""Exercise the actual desktop runtime with a small local application fixture."""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from fixtures.processes import RUNTIME_SERVER, cleanup_process, free_port, wait_for


@unittest.skipUnless(
    shutil.which("bun"), "Bun is required for executable launcher integration"
)
class LauncherTest(unittest.TestCase):
    def test_native_shell_quit_drains_but_lost_pipe_keeps_monitoring(self):
        for command in (b"quit\n", None):
            with (
                self.subTest(command=command),
                tempfile.TemporaryDirectory(prefix="ai-host-") as temporary,
            ):
                folder = Path(temporary)
                port = free_port()
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
                    [shutil.which("bun"), str(RUNTIME_SERVER)],
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
                        wait_for(
                            process,
                            lambda folder=folder: (
                                folder / "data/launcher-disconnected"
                            ).exists(),
                            log_path,
                        )
                        self.assertIsNone(process.poll())
                        self.assertFalse((folder / "data/drained").exists())
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/", timeout=2
                        ) as response:
                            self.assertEqual(response.read(), b"fixture dashboard")
                        with subprocess.Popen(
                            [shutil.which("bun"), str(RUNTIME_SERVER), "--quit"],
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        ) as quitting:
                            process.wait(timeout=10)
                            _, errors = quitting.communicate(timeout=10)
                            self.assertEqual(quitting.returncode, 0, errors.decode())
                    process.wait(timeout=10)
                    self.assertEqual(process.returncode, 0, log_path.read_text())
                    self.assertEqual((folder / "data/drained").read_text(), "200")
                    self.assertEqual(
                        (folder / "data/shutdown-reasons").read_text().strip(),
                        "Native launcher sent an explicit quit command"
                        if command
                        else "Authenticated desktop quit request",
                    )
                finally:
                    cleanup_process(process)
                    log.close()

    def test_only_a_native_shell_is_told_whether_monitoring_is_on(self):
        for host in ("1", ""):
            with (
                self.subTest(host=host),
                tempfile.TemporaryDirectory(prefix="ai-awake-") as temporary,
            ):
                folder = Path(temporary)
                port = free_port()
                log_path = folder / "launcher.log"
                with log_path.open("w") as log:
                    process = subprocess.Popen(
                        [shutil.which("bun"), str(RUNTIME_SERVER)],
                        env={
                            **os.environ,
                            "AIDETECTOR_DATA_DIR": str(folder / "data"),
                            "AIDETECTOR_DESKTOP_HOST": host,
                            "HOST": "127.0.0.1",
                            "PORT": str(port),
                            "OPEN_BROWSER": "false",
                        },
                        stdin=subprocess.PIPE,
                        stdout=log,
                        stderr=log,
                    )
                    try:
                        wait_for(
                            process,
                            lambda log_path=log_path: (
                                "AI Detector is ready" in log_path.read_text()
                            ),
                            log_path,
                        )
                        for path in ("monitoring-on", "monitoring-off", ""):
                            urllib.request.urlopen(
                                f"http://127.0.0.1:{port}/{path}", timeout=2
                            ).close()
                        # The last request's own line follows whatever the first two said.
                        wait_for(
                            process,
                            lambda log_path=log_path: (
                                log_path.read_text().count("Dashboard request received")
                                == 3
                            ),
                            log_path,
                        )
                        told = [
                            line
                            for line in log_path.read_text().splitlines()
                            if line.startswith("AI_DETECTOR_MONITORING")
                        ]
                        self.assertEqual(
                            told,
                            ["AI_DETECTOR_MONITORING on", "AI_DETECTOR_MONITORING off"]
                            if host
                            else [],
                        )
                    finally:
                        cleanup_process(process)

    def test_second_launch_does_not_initialize_another_server_and_quit_is_graceful(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="ai-launcher-") as temporary:
            folder = Path(temporary)
            port = free_port()
            env = {
                **os.environ,
                "AIDETECTOR_DATA_DIR": str(folder / "data"),
                "HOST": "127.0.0.1",
                "PORT": str(port),
                "OPEN_BROWSER": "false",
            }
            arguments = [shutil.which("bun"), str(RUNTIME_SERVER)]
            with (folder / "log").open("w") as log:
                process = subprocess.Popen(arguments, env=env, stdout=log, stderr=log)
                try:
                    starts = folder / "data/starts"
                    # Startup must initialize without a browser request.
                    wait_for(process, starts.exists, folder / "log")
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
                    cleanup_process(process)

    def data_folder(self) -> Path:
        temporary = tempfile.TemporaryDirectory(prefix="ai-port-")
        self.addCleanup(temporary.cleanup)
        data = Path(temporary.name) / "data"
        data.mkdir()
        return data

    def start_without_port(self, data: Path) -> tuple[subprocess.Popen, Path]:
        """Start the runtime as the native menu does, which leaves the port to it."""
        log_path = data.parent / "launcher.log"
        log = log_path.open("w")
        self.addCleanup(log.close)
        env = {
            **os.environ,
            "AIDETECTOR_DATA_DIR": str(data),
            "AIDETECTOR_DESKTOP_HOST": "1",
            "HOST": "127.0.0.1",
            "OPEN_BROWSER": "false",
        }
        env.pop("PORT", None)
        process = subprocess.Popen(
            [shutil.which("bun"), str(RUNTIME_SERVER)],
            env=env,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
        )
        self.addCleanup(cleanup_process, process)
        return process, log_path

    def test_the_dashboard_keeps_its_port_and_leaves_one_another_program_took(self):
        data = self.data_folder()
        settings = data / "app.json"
        port = free_port()
        settings.write_text(json.dumps({"language": "nl", "port": port}))
        process, log_path = self.start_without_port(data)
        wait_for(
            process, lambda: "AI Detector is ready" in log_path.read_text(), log_path
        )
        self.assertEqual(published_port(data), port)
        cleanup_process(process)

        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", port))
            occupied.listen()
            process, log_path = self.start_without_port(data)
            wait_for(
                process,
                lambda: "AI Detector is ready" in log_path.read_text(),
                log_path,
            )
            moved = published_port(data)
            self.assertNotEqual(moved, port)
            self.assertEqual(
                json.loads(settings.read_text()), {"language": "nl", "port": moved}
            )
            with urllib.request.urlopen(
                f"http://127.0.0.1:{moved}/", timeout=2
            ) as response:
                self.assertEqual(response.read(), b"fixture dashboard")

    def test_a_copy_that_is_still_starting_is_not_joined_by_a_second(self):
        data = self.data_folder()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            (data / "app.json").write_text(json.dumps({"port": port}))
            # What a copy writes once it holds the port, before it can answer.
            (data / "desktop-instance.json").write_text(
                json.dumps({"port": port, "token": "starting", "pid": os.getpid()})
            )
            process, log_path = self.start_without_port(data)
            self.assertNotEqual(process.wait(timeout=15), 0)
        self.assertIn(f"port {port}", log_path.read_text())
        self.assertFalse((data / "starts").exists())


def published_port(data: Path) -> int:
    return json.loads((data / "desktop-instance.json").read_text())["port"]
