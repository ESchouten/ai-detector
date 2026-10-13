import json
import os
import socket
import sys
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import certifi
import cv2
import numpy as np
import pytest
import requests
from ultralytics.utils import downloads
from urllib3.exceptions import MaxRetryError, NameResolutionError

from aidetector.adapters.inference.model_assets import resolve_model_path
from aidetector.bootstrap import run_application
from aidetector.cli import main
from aidetector.configuration import Config
from tests.support.https import enable_https
from tests.support.onnx_model import write_detection_model
from tests.support.status import status_records

_CONNECT = socket.socket.connect


@dataclass
class Asset:
    body: bytes
    status: int = 200
    declared_size: int | None = None


def full_traceback(failure):
    return "".join(traceback.format_exception(failure.type, failure.value, failure.tb))


@pytest.fixture(params=["http", "https"])
def asset_server(monkeypatch, tmp_path, request):
    assets: dict[str, Asset] = {}
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            asset = assets[self.path]
            self.send_response(asset.status)
            size = (
                len(asset.body) if asset.declared_size is None else asset.declared_size
            )
            self.send_header("Content-Length", str(size))
            self.end_headers()
            self.wfile.write(asset.body)
            self.close_connection = True

        def log_message(self, *args):
            pass

    def connect_local(connection, address):
        assert address[0] == "127.0.0.1", "Only the local asset server is allowed"
        return _CONNECT(connection, address)

    monkeypatch.setattr(socket.socket, "connect", connect_local)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        if request.param == "https":
            certificate = tmp_path / "server-ca.pem"
            enable_https(server, certificate)
            monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield f"{request.param}://127.0.0.1:{server.server_port}", assets, requests
        finally:
            server.shutdown()
            thread.join()


def test_model_paths_are_relative_to_config_and_stock_downloads_have_a_managed_directory(
    tmp_path,
):
    model = tmp_path / "custom.onnx"
    model.write_bytes(b"existing")
    cache = tmp_path / "runtime" / "models"
    assert resolve_model_path("custom.onnx", tmp_path, cache) == str(model)
    assert resolve_model_path("weights/custom.pt", tmp_path, cache) == str(
        tmp_path / "weights/custom.pt"
    )
    assert resolve_model_path("yolo11n.pt", tmp_path, cache) == str(
        cache / "yolo11n.pt"
    )


def test_stock_model_path_keeps_ultralytics_automatic_asset_download(
    tmp_path, monkeypatch
):
    transfers = []

    def download(url, file, **kwargs):
        transfers.append(url)
        Path(file).write_bytes(b"checkpoint")

    monkeypatch.setattr(downloads, "safe_download", download)
    model = resolve_model_path("yolo11n.pt", tmp_path, tmp_path / "models")
    assert downloads.attempt_download_asset(model) == model
    assert downloads.attempt_download_asset(model) == model
    assert len(transfers) == 1
    assert transfers[0].endswith("/yolo11n.pt")
    assert Path(model).read_bytes() == b"checkpoint"


def test_download_reuses_cache_and_separates_urls_with_the_same_filename(
    tmp_path, asset_server
):
    base, assets, requests = asset_server
    first = "/one/model.onnx?token=secret"
    second = "/two/model.onnx?token=other"
    assets[first] = Asset(b"first model")
    assets[second] = Asset(b"second model")
    cache = tmp_path / "models"
    model = Path(resolve_model_path(base + first, tmp_path, cache))
    assert model.read_bytes() == b"first model"
    assert resolve_model_path(base + first, tmp_path, cache) == str(model)
    other = Path(resolve_model_path(base + second, tmp_path, cache))
    assert other.read_bytes() == b"second model"
    assert other != model
    assert requests == [first, second]
    assert set(cache.rglob("*.onnx")) == {model, other}
    assert not list(cache.rglob("download-*"))


@pytest.mark.parametrize("asset", [Asset(b""), Asset(b"partial", declared_size=100)])
def test_empty_and_partial_downloads_are_rejected_without_caching(
    tmp_path, asset_server, asset
):
    base, assets, requests = asset_server
    assets["/model.onnx"] = asset
    cache = tmp_path / "models"
    with pytest.raises(RuntimeError, match="complete file"):
        resolve_model_path(base + "/model.onnx", tmp_path, cache)
    assert requests == ["/model.onnx"]
    assert not list(cache.rglob("*.onnx"))
    assert not list(cache.rglob("download-*"))


def test_failed_download_can_be_retried_without_reusing_a_partial_file(
    tmp_path, asset_server
):
    base, assets, requests = asset_server
    path = "/model.pt?token=secret"
    assets[path] = Asset(b"unavailable", status=503)
    cache = tmp_path / "models"
    with pytest.raises(RuntimeError, match="download failed") as failure:
        resolve_model_path(base + path, tmp_path, cache)
    assert "secret" not in full_traceback(failure)
    assert not list(cache.rglob("*.pt"))
    assets[path] = Asset(b"complete checkpoint")
    model = Path(resolve_model_path(base + path, tmp_path, cache))
    assert model.read_bytes() == b"complete checkpoint"
    assert requests == [path, path]


def test_startup_reports_actionable_download_failure_without_losing_its_cause(
    tmp_path, asset_server
):
    base, assets, _ = asset_server
    assets["/model.onnx?token=secret"] = Asset(b"unavailable", status=503)
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "rtsp://camera.example.test/live"},
                    "yolo": {"model": base + "/model.onnx?token=secret"},
                }
            ]
        }
    )
    observations = []
    with pytest.raises(RuntimeError, match="download failed"):
        run_application(config, tmp_path, tmp_path, report_status=observations.append)
    failure = observations[-1]
    assert failure.kind == "preparation_failed"
    assert failure.rule_id == "detector-1"
    assert "HTTP 503" in failure.message
    assert "secret" not in repr(observations)
    assert all(event.kind != "ready" for event in observations)


@pytest.mark.parametrize("asset_server", ["https"], indirect=True)
@pytest.mark.parametrize("custom_ca", [False, True])
def test_packaged_startup_downloads_over_https_with_bundled_or_custom_certificates(
    tmp_path, monkeypatch, asset_server, custom_ca, capsys
):
    base, assets, requests = asset_server
    # Substitute a test CA for the public bundle; use real TLS and SDK inference.
    certificate = os.environ["SSL_CERT_FILE"]
    if not custom_ca:
        monkeypatch.delenv("SSL_CERT_FILE")
        monkeypatch.setattr(certifi, "where", lambda: certificate)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    model = tmp_path / "fixture.onnx"
    write_detection_model(model)
    assets["/model.onnx"] = Asset(model.read_bytes())
    image = tmp_path / "input.png"
    assert cv2.imwrite(str(image), np.zeros((64, 64, 3), dtype=np.uint8))
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "onnx": {"provider": "CPUExecutionProvider"},
                "detectors": [
                    {
                        "detection": {"source": str(image)},
                        "yolo": {"model": base + "/model.onnx", "imgsz": 64},
                    }
                ],
            }
        )
    )
    assert main(["--config", str(config), "--status-json"]) == 0
    assert requests == ["/model.onnx"]
    records = status_records(capsys.readouterr().out)
    assert any(record["event"] == "inference" for record in records)


@pytest.mark.parametrize("asset_server", ["https"], indirect=True)
def test_untrusted_https_certificate_is_rejected_with_a_useful_diagnostic(
    tmp_path, monkeypatch, asset_server
):
    base, _, requests = asset_server
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    observations = []
    cache = tmp_path / "models"
    with pytest.raises(RuntimeError, match="HTTPS certificate") as failure:
        resolve_model_path(
            base + "/model.onnx?token=secret", tmp_path, cache, observations.append
        )
    assert observations[-1].kind == "preparation_failed"
    assert "HTTPS certificate" in observations[-1].message
    assert "secret" not in full_traceback(failure)
    assert requests == []
    assert not list(cache.rglob("*.onnx"))


@pytest.mark.parametrize(
    "error, diagnostic",
    [
        (
            requests.ConnectionError(
                MaxRetryError(
                    None,
                    "secret-url",
                    NameResolutionError(
                        "secret-host",
                        None,
                        socket.gaierror(-2, "secret-host"),
                    ),
                )
            ),
            "address could not be resolved",
        ),
        (requests.ConnectTimeout("secret-url"), "timed out"),
        (requests.ConnectionError("secret-url"), "Check the model URL"),
    ],
)
def test_download_reports_transport_failures_without_exposing_credentials(
    tmp_path, monkeypatch, error, diagnostic
):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(requests, "get", fail)
    observations = []
    with pytest.raises(RuntimeError, match=diagnostic) as failure:
        resolve_model_path(
            "https://user:secret@host/model.onnx?token=secret",
            tmp_path,
            tmp_path / "models",
            observations.append,
        )
    assert diagnostic in observations[-1].message
    assert "secret" not in repr(observations)
    assert "secret" not in full_traceback(failure)
