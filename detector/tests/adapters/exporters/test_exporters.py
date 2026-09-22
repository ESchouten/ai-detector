import json
from datetime import datetime

import cv2
import numpy as np
import pytest
import requests

from aidetector.adapters.exporters.telegram import TelegramExporter
from aidetector.adapters.exporters.webhook import WebhookExporter
from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.media.images import encode_jpeg
from aidetector.application.delivery import Destination, EventDelivery
from aidetector.application.ports import DeliveryError
from aidetector.configuration import TelegramConfig, WebhookConfig
from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    Observation,
    ValidationResult,
    ValidationStatus,
)
from aidetector.domain.policy import Cooldown, ExportPolicy


@pytest.fixture
def result():
    observation = Observation(
        datetime(2026, 1, 1), np.zeros((24, 32, 3), dtype=np.uint8), {"cow": 0.9}
    )
    return EventResult(
        DetectionEvent("camera", (observation,)),
        ValidationResult(ValidationStatus.UNVALIDATED),
    )


@pytest.fixture
def requests_sent(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"ok": true}'
        return response

    monkeypatch.setattr(requests, "request", request)
    return calls


def test_webhook_none_and_explicit_body_do_not_render_media(result, requests_sent):
    for body in (None, "fixed-body"):
        exporter = WebhookExporter(
            WebhookConfig(url="https://example.test", data_type="none", body=body),
            EventMedia(),
        )
        exporter.export(result)
        _, _, request = requests_sent[-1]
        assert request["data"] == body
        assert request["json"] is None
        assert request["files"] is None
        assert request["timeout"] == 30


def test_webhook_base64_includes_metadata_and_selected_media(result, requests_sent):
    exporter = WebhookExporter(
        WebhookConfig(
            url="https://example.test",
            data_type="base64",
            include_image=True,
            token="secret",
            headers={"X-Test": "value"},
        ),
        EventMedia(),
    )
    exporter.export(result)
    request = requests_sent[0][2]
    assert request["json"]["confidence"] == 0.9
    assert request["json"]["validated"] is None
    assert request["json"]["image"].startswith("/9j/")
    assert "crop" not in request["json"]
    assert request["headers"] == {"X-Test": "value", "Authorization": "secret"}


def test_webhook_multipart_uses_matching_file_names(result, requests_sent):
    exporter = WebhookExporter(
        WebhookConfig(
            url="https://example.test", include_image=True, include_plot=True
        ),
        EventMedia(),
    )
    exporter.export(result)
    request = requests_sent[0][2]
    assert set(request["files"]) == {"image", "photo"}
    assert request["files"]["image"][2] == "image/jpeg"
    assert request["data"]["confidence"] == 0.9


def test_transport_failure_is_observable_without_credentials(result, monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("https://example.test/private-token")

    monkeypatch.setattr(requests, "request", fail)
    exporter = WebhookExporter(
        WebhookConfig(url="https://example.test/private-token", data_type="none"),
        EventMedia(),
    )
    with pytest.raises(DeliveryError) as raised:
        exporter.export(result)
    assert "ConnectionError" in str(raised.value)
    assert "private-token" not in str(raised.value)


@pytest.mark.parametrize(
    "options, method, names",
    [
        ({"include_video": False}, "sendMessage", set()),
        ({"include_video": False, "include_image": True}, "sendPhoto", {"photo"}),
        ({"include_video": True}, "sendVideo", {"video"}),
        (
            {"include_video": True, "include_image": True},
            "sendMediaGroup",
            {"image", "video"},
        ),
    ],
)
def test_telegram_selects_message_single_media_or_album(
    result, requests_sent, monkeypatch, options, method, names
):
    monkeypatch.setattr(
        "aidetector.adapters.media.event_media.encode_video", lambda *a, **kw: b"mp4"
    )
    exporter = TelegramExporter(
        TelegramConfig(token="token", chat="chat", **options), EventMedia()
    )
    exporter.export(result)
    _, url, request = requests_sent[0]
    assert url.endswith("/" + method)
    assert set(request["files"]) == names
    assert request["data"]["chat_id"] == "chat"
    if method == "sendMediaGroup":
        media = json.loads(request["data"]["media"])
        assert len(media) == 2
        assert media[0]["caption"].startswith("90%")
        assert {item["media"] for item in media} == {"attach://image", "attach://video"}


def test_telegram_video_is_rendered_once_and_notification_cadence_is_preserved(
    result, requests_sent, monkeypatch
):
    encodings = []

    def encode(*args, **kwargs):
        encodings.append(kwargs)
        return b"mp4"

    monkeypatch.setattr("aidetector.adapters.media.event_media.encode_video", encode)
    exporter = TelegramExporter(
        TelegramConfig(token="token", chat="chat", alert_every=2), EventMedia()
    )
    exporter.export(result)
    exporter.export(result)
    assert len(encodings) == 1
    assert encodings[0]["data_max"] == 12_000_000
    assert [
        request[2]["data"]["disable_notification"] for request in requests_sent
    ] == ["true", "false"]


@pytest.mark.parametrize(
    "body, message",
    [
        (b"not JSON", "Telegram returned an invalid response"),
        (b"{}", "Telegram returned an invalid response"),
        (b"[]", "Telegram returned an invalid response"),
        (b'{"ok": "true"}', "Telegram did not accept the message"),
        (b'{"ok": 1}', "Telegram did not accept the message"),
        (b'{"ok": false}', "Telegram did not accept the message"),
    ],
)
def test_telegram_requires_an_explicit_boolean_acceptance(
    result, monkeypatch, body, message
):
    def request(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = body
        return response

    monkeypatch.setattr(requests, "request", request)
    exporter = TelegramExporter(
        TelegramConfig(token="token", chat="chat", include_video=False), EventMedia()
    )

    with pytest.raises(DeliveryError, match=message):
        exporter.export(result)


@pytest.mark.parametrize("failure_kind", ["connection", "http_status", "acceptance"])
def test_transport_failure_keeps_independent_destinations_and_safe_diagnostics(
    result, monkeypatch, caplog, failure_kind
):
    calls = []
    telegram_url = "https://api.telegram.org/botprivate-token/sendMessage"
    webhook_url = "https://example.test/webhook"

    def request(method, url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"ok": true}'
        if url == telegram_url:
            if failure_kind == "connection":
                raise requests.ConnectionError(f"Connection failed: {url}")
            if failure_kind == "http_status":
                response.status_code = 503
            response._content = b'{"ok": false, "description": "private-token"}'
        return response

    monkeypatch.setattr(requests, "request", request)
    media = EventMedia()
    delivery = EventDelivery(
        (
            Destination(
                "telegram",
                TelegramExporter(
                    TelegramConfig(
                        token="private-token", chat="chat", include_video=False
                    ),
                    media,
                ),
                ExportPolicy(),
            ),
            Destination(
                "webhook",
                WebhookExporter(
                    WebhookConfig(url=webhook_url, data_type="none"), media
                ),
                ExportPolicy(),
            ),
        ),
        Cooldown(),
    )

    report = delivery.deliver(result.event)

    assert calls == [telegram_url, webhook_url]
    assert report.delivered == ("webhook",)
    [failure] = report.failures
    assert failure.destination == "telegram"
    assert failure.message in caplog.text
    assert "private-token" not in failure.message + caplog.text


@pytest.mark.parametrize("album", [False, True])
def test_telegram_compresses_large_photos_to_the_photo_limit(requests_sent, album):
    image = np.random.default_rng(42).integers(0, 256, (3600, 3600, 3), dtype=np.uint8)
    assert len(encode_jpeg(image, quality=90)) > 10_000_000
    observation = Observation(datetime(2026, 1, 1), image, {"cow": 0.9})
    result = EventResult(
        DetectionEvent("camera", (observation,)),
        ValidationResult(ValidationStatus.UNVALIDATED),
    )
    exporter = TelegramExporter(
        TelegramConfig(
            token="token",
            chat="chat",
            include_image=True,
            include_plot=album,
            include_video=False,
        ),
        EventMedia(),
    )
    exporter.export(result)

    _, url, request = requests_sent[0]
    assert url.endswith("/sendMediaGroup" if album else "/sendPhoto")
    assert len(request["files"]) == (2 if album else 1)
    for _, content, content_type in request["files"].values():
        assert content_type == "image/jpeg"
        assert 0 < len(content) <= 10_000_000


def test_ffmpeg_discovery_failure_does_not_stop_independent_delivery(
    result, requests_sent, monkeypatch
):
    def unavailable():
        raise RuntimeError("No ffmpeg exe could be found")

    monkeypatch.setattr("aidetector.adapters.media.video.get_ffmpeg_exe", unavailable)
    delivery = EventDelivery(
        (
            Destination(
                "telegram",
                TelegramExporter(
                    TelegramConfig(token="token", chat="chat"), EventMedia()
                ),
                ExportPolicy(),
            ),
            Destination(
                "webhook",
                WebhookExporter(
                    WebhookConfig(url="https://example.test", data_type="none"),
                    EventMedia(),
                ),
                ExportPolicy(),
            ),
        ),
        Cooldown(),
    )
    for _ in range(2):
        report = delivery.deliver(result.event)
        assert report.delivered == ("webhook",)
        [failure] = report.failures
        assert failure.destination == "telegram"
        assert "FFmpeg is unavailable" in failure.message
    assert len(requests_sent) == 2


@pytest.mark.parametrize("raises", [False, True])
def test_jpeg_codec_failure_is_reported_and_later_events_still_deliver(
    result, requests_sent, monkeypatch, raises
):
    def unavailable(*args, **kwargs):
        if raises:
            raise cv2.error("JPEG codec unavailable")
        return False, None

    monkeypatch.setattr("aidetector.adapters.media.images.cv2.imencode", unavailable)
    delivery = EventDelivery(
        (
            Destination(
                "image",
                WebhookExporter(
                    WebhookConfig(url="https://example.test", include_image=True),
                    EventMedia(),
                ),
                ExportPolicy(),
            ),
            Destination(
                "metadata",
                WebhookExporter(
                    WebhookConfig(url="https://example.test", data_type="none"),
                    EventMedia(),
                ),
                ExportPolicy(),
            ),
        ),
        Cooldown(),
    )
    for _ in range(2):
        report = delivery.deliver(result.event)
        assert report.delivered == ("metadata",)
        assert len(report.failures) == 1
        assert report.failures[0].destination == "image"
        assert "JPEG encoding failed" in report.failures[0].message
    assert len(requests_sent) == 2
