"""Boot the complete download with a local image; verify a real archived event."""

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def wait_for_setup(process: subprocess.Popen, url: str, deadline: float) -> None:
    while (remaining := deadline - time.monotonic()) > 0:
        if process.poll() is not None:
            raise RuntimeError(
                f"Application exited before setup was available (status {process.returncode})"
            )
        try:
            with urllib.request.urlopen(url, timeout=min(5, remaining)) as response:
                assert b"AI Detector" in response.read(), (
                    "Setup page content is missing"
                )
            return
        except urllib.error.HTTPError as error:
            error.close()
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    raise TimeoutError("Setup page never became available")


def wait_for_detection(process: subprocess.Popen, data: Path, deadline: float) -> None:
    while (remaining := deadline - time.monotonic()) > 0:
        if process.poll() is not None:
            raise RuntimeError(
                f"Application exited before creating a detection (status {process.returncode})"
            )
        events = list((data / "detections").glob("*/*/*/metadata.json"))
        if events:
            assert json.loads(events[0].read_text(encoding="utf-8"))["detections"] == 1
            assert events[0].with_name("best.jpg").stat().st_size > 0
            return
        time.sleep(min(0.2, remaining))
    raise TimeoutError("Bundled detector did not create a detection")


def stop_application(process: subprocess.Popen, timeout: float = 40) -> None:
    if process.poll() is not None:
        raise RuntimeError(
            f"Application exited before shutdown (status {process.returncode})"
        )
    process.stdin.write(b"quit\n")
    process.stdin.flush()
    try:
        status = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("Application did not finish graceful shutdown") from error
    if status != 0:
        raise RuntimeError(f"Application shutdown failed (status {status})")


def smoke(folder: Path) -> None:
    app = folder / "AI Detector.app"
    launch = (
        (app / "Contents/MacOS/ai-detector-web")
        if app.exists()
        else folder / ("ai-detector-web.exe" if os.name == "nt" else "AI Detector")
    )
    with tempfile.TemporaryDirectory(prefix="ai-detector-bundle-") as temporary:
        data = Path(temporary)
        # A 16 x 16 uncompressed BMP needs no third-party image library.
        pixels = bytes([80, 100, 120]) * 16 * 16
        header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
        header += struct.pack(
            "<IiiHHIIiiII", 40, 16, 16, 1, 24, 0, len(pixels), 0, 0, 0, 0
        )
        (data / "input.bmp").write_bytes(header + pixels)
        (data / "config.json").write_text(
            json.dumps(
                {
                    "detectors": [
                        {
                            "detection": {"source": "input.bmp"},
                            "exporters": {"disk": {}},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (data / "runtime.json").write_text(
            json.dumps({"enabled": True, "mode": "native"}), encoding="utf-8"
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {
            **os.environ,
            "AIDETECTOR_DATA_DIR": str(data),
            "AIDETECTOR_DESKTOP_HOST": "1",
            "OPEN_BROWSER": "false",
            "HOST": "127.0.0.1",
            "PORT": str(port),
        }
        with (data / "web.log").open("w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(launch.resolve())],
                env=env,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 90
                wait_for_setup(process, f"http://127.0.0.1:{port}/setup", deadline)
                wait_for_detection(process, data, deadline)
                stop_application(process)
                print(
                    "Application payload smoke passed: setup, detector launch, image archive and graceful shutdown."
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                process.stdin.close()
                log.seek(0)
                print(log.read())


if __name__ == "__main__":
    smoke(Path(sys.argv[1]))
