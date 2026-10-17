import os
import socket

import pytest

# Configure SDK imports without reading credentials or fetching provider metadata.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
os.environ["ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS"] = "1"
os.environ["YOLO_AUTOINSTALL"] = "false"


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must replace external I/O at the adapter boundary")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
