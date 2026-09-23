"""Bounded process waits shared by desktop integration tests."""

import subprocess
import time
from collections.abc import Callable
from pathlib import Path


def wait_for(
    process: subprocess.Popen,
    predicate: Callable[[], bool],
    log: Path,
    timeout: float = 15,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        if process.poll() is not None:
            raise AssertionError(
                f"Process exited with status {process.returncode}:\n{log.read_text(errors='replace')}"
            )
        time.sleep(0.02)
    raise AssertionError(
        f"Process did not become ready within {timeout}s:\n{log.read_text(errors='replace')}"
    )


def cleanup_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
        process.wait(timeout=10)
    if process.stdin:
        process.stdin.close()
