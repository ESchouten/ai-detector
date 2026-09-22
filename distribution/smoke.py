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


def smoke(folder: Path) -> None:
    launch = next(folder.glob("AI Detector*"))
    with tempfile.TemporaryDirectory(prefix="ai-detector-bundle-") as temporary:
        data = Path(temporary)
        # A 16 x 16 uncompressed BMP needs no third-party image library.
        pixels = bytes([80, 100, 120]) * 16 * 16
        header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
        header += struct.pack("<IiiHHIIiiII", 40, 16, 16, 1, 24, 0, len(pixels), 0, 0, 0, 0)
        (data / "input.bmp").write_bytes(header + pixels)
        (data / "config.json").write_text(json.dumps({"detectors": [{"detection": {"source": "input.bmp"}, "exporters": {"disk": {}}}]}))
        (data / "runtime.json").write_text(json.dumps({"enabled": True, "mode": "native"}))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {**os.environ, "AIDETECTOR_DATA_DIR": str(data), "OPEN_BROWSER": "false", "HOST": "127.0.0.1", "PORT": str(port)}
        with (data / "web.log").open("w+") as log:
            process = subprocess.Popen([str(launch.resolve())], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Application exited before setup was available")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/setup", timeout=5) as response:
                            assert b"Your detector" in response.read()
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.2)
                else:
                    raise TimeoutError("Setup page never became available")
                while time.monotonic() < deadline:
                    events = list((data / "detections").glob("*/*/*/metadata.json"))
                    if events:
                        assert json.loads(events[0].read_text())["detections"] == 1
                        assert events[0].with_name("best.jpg").stat().st_size > 0
                        print("Complete application smoke passed: setup page, automatic native launch, real image archive.")
                        return
                    time.sleep(0.2)
                raise TimeoutError("Bundled detector did not create a detection")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                log.seek(0)
                print(log.read())


if __name__ == "__main__":
    smoke(Path(sys.argv[1]))
