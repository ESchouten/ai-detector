import io
import logging
import socket
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from ultralytics.utils import downloads

from aidetector.adapters.inference.model_assets import resolve_model_path
from aidetector.bootstrap import run_application
from aidetector.configuration import Config

_CONNECT = socket.socket.connect


@dataclass
class Asset:
    body: bytes
    status: int = 200
    declared_size: int | None = None


@pytest.fixture
def asset_server(monkeypatch):
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
    # Do not let the SDK's error diagnostic probe Internet connectivity.
    monkeypatch.setattr(downloads, "is_online", lambda: True)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", assets, requests
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


def test_sdk_download_reuses_cache_and_separates_urls_with_the_same_filename(
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
def test_sdk_rejects_empty_and_partial_downloads_without_caching(
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


def test_failed_sdk_download_can_be_retried_without_reusing_a_partial_file(
    tmp_path, asset_server
):
    base, assets, requests = asset_server
    path = "/model.pt?token=secret"
    assets[path] = Asset(b"unavailable", status=503)
    cache = tmp_path / "models"
    with pytest.raises(RuntimeError, match="download failed") as failure:
        resolve_model_path(base + path, tmp_path, cache)
    assert "secret" not in "".join(
        traceback.format_exception(failure.type, failure.value, failure.tb)
    )
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
    assert "internet" in failure.message
    assert "secret" not in repr(observations)
    assert all(event.kind != "ready" for event in observations)


def test_sdk_diagnostics_hide_credentials_without_muting_other_threads(
    tmp_path, monkeypatch
):
    sdk_logger = logging.getLogger("ultralytics")
    original_filters = list(sdk_logger.filters)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    sdk_logger.addHandler(handler)

    def fail(*args, **kwargs):
        sdk_logger.warning("https://user:secret@host/model.onnx?token=secret")
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(sdk_logger.warning, "Other detector diagnostic").result(
                timeout=2
            )
        raise ConnectionError("Download failed for user:secret and token=secret")

    monkeypatch.setattr(downloads, "safe_download", fail)
    try:
        with pytest.raises(RuntimeError, match="download failed") as failure:
            resolve_model_path(
                "https://user:secret@host/model.onnx?token=secret",
                tmp_path,
                tmp_path / "models",
            )
    finally:
        sdk_logger.removeHandler(handler)
    assert sdk_logger.filters == original_filters
    assert "Other detector diagnostic" in output.getvalue()
    diagnostic = output.getvalue() + "".join(
        traceback.format_exception(failure.type, failure.value, failure.tb)
    )
    assert "secret" not in diagnostic
    assert not list((tmp_path / "models").rglob("*.onnx"))
