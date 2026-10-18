"""Bounded process waits and the runtime fixture shared by desktop integration tests."""

import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

RUNTIME_SERVER = (
    Path(__file__).resolve().parents[2] / "web/desktop/fixtures/runtime-server.ts"
)
TIMEOUT = 15


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(
    process: subprocess.Popen, predicate: Callable[[], bool], log: Path
) -> None:
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if predicate():
            return
        # Re-check after an exit: the process may have met the condition just before exiting.
        if process.poll() is not None and not predicate():
            raise AssertionError(
                f"Process exited with status {process.returncode}:\n{log.read_text(errors='replace')}"
            )
        time.sleep(0.02)
    raise AssertionError(
        f"Process did not become ready within {TIMEOUT}s:\n{log.read_text(errors='replace')}"
    )


def cleanup_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
        process.wait(timeout=10)
    if process.stdin:
        process.stdin.close()
