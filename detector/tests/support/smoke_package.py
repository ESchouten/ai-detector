"""Exercise a distribution with generated models/media and a local fake AI/HTTP service.

Run from detector/: python -m tests.support.smoke_package /path/to/executable [--model-format pt]
No camera, external model download, external API, or real credentials are used.
"""

import argparse
import json
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import cv2
import numpy as np

from tests.support.onnx_model import write_detection_model


def assert_verification_schema(request: dict) -> None:
    response_format = request["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["required"] == ["detected"]
    assert set(schema["properties"]) == {"detected"}
    assert schema["properties"]["detected"]["type"] == "boolean"
    assert schema["additionalProperties"] is False


def verify(executable: Path, model_format: str = "onnx") -> None:
    requests: list[tuple[str, dict]] = []

    class LocalService(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != f"/{model.name}":
                self.send_error(404)
                return
            requests.append((self.path, {}))
            payload = model.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if self.path == "/v1/chat/completions":
                result = {
                    "id": "local-test",
                    "model": "local-test",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"detected": True}),
                            },
                        }
                    ],
                }
            else:
                result = {"ok": True}
            payload = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with tempfile.TemporaryDirectory(prefix="aidetector-package-smoke-") as directory:
        root = Path(directory)
        model = root / f"detector.{model_format}"
        if model_format == "pt":
            from ultralytics import YOLO

            YOLO("yolo11n.yaml").save(model)
        else:
            write_detection_model(model)
        for name in ("one.png", "two.png"):
            assert cv2.imwrite(str(root / name), np.zeros((64, 64, 3), dtype=np.uint8))
        server = ThreadingHTTPServer(("127.0.0.1", 0), LocalService)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        config = {
            "onnx": {"provider": "CPUExecutionProvider", "winml": False},
            "health": {
                "url": base_url + "/health",
                "method": "POST",
                "body": "{}",
                "interval": 60,
            },
            "detectors": [
                {
                    "detection": {"source": ["one.png", "two.png"]},
                    "yolo": {
                        "model": f"{base_url}/{model.name}",
                        "confidence": {"cow": 0.5} if model_format == "onnx" else 0,
                        "imgsz": 64,
                        "frames_min": 1,
                        "tracking": model_format == "onnx",
                    },
                    "vlm": {
                        "model": "openai/local-test",
                        "url": base_url + "/v1",
                        "key": "local-test-key",
                        "prompt": "Is there a cow?",
                        "strategy": "IMAGE",
                        "attempts": 1,
                    },
                    "exporters": {
                        "disk": {"directory": "smoke"},
                        "webhook": {
                            "url": base_url + "/events",
                            "data_type": "base64",
                            "include_image": True,
                            "include_video": True,
                        },
                    },
                }
            ],
        }
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        try:
            process = subprocess.run(
                [str(executable), "--config", str(config_path)],
                cwd=root,
                env={
                    **os.environ,
                    "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                    "YOLO_CONFIG_DIR": str(root / "yolo"),
                },
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        assert process.returncode == 0, process.stdout + process.stderr
        assert [path for path, _ in requests].count(f"/{model.name}") == 1
        [cached] = (root / "models").glob(f"*/{model.name}")
        assert cached.read_bytes() == model.read_bytes()
        archives = list((root / "detections/smoke/approved").glob("*/metadata.json"))
        assert len(archives) == 2, process.stdout + process.stderr
        for path in archives:
            assert json.loads(path.read_text())["validated"] is True
            assert cv2.imread(str(path.parent / "best.jpg")).shape == (64, 64, 3)
            capture = cv2.VideoCapture(str(path.parent / "video.mp4"))
            try:
                assert capture.isOpened() and capture.read()[0]
            finally:
                capture.release()
        ai_requests = [
            body for path, body in requests if path == "/v1/chat/completions"
        ]
        webhooks = [body for path, body in requests if path == "/events"]
        assert len(ai_requests) == len(webhooks) == 2
        assert any(path == "/health" for path, _ in requests)
        for body in ai_requests:
            assert_verification_schema(body)
        assert all(
            body["validated"] is True and body["image"] and body["video"]
            for body in webhooks
        )
    print(
        f"Executable passed ({model_format}): model loading, two-source inference, local VLM verification, JPEG/MP4 archives, HTTP delivery, health monitoring, and EOF shutdown."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--model-format", choices=("onnx", "pt"), default="onnx")
    arguments = parser.parse_args()
    verify(arguments.executable.resolve(), arguments.model_format)
