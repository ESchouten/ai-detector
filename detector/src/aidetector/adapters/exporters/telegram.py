import json
from collections.abc import Callable
from datetime import datetime, time

from aidetector.adapters.http import Files, send_request
from aidetector.adapters.media import MediaError
from aidetector.adapters.media.event_media import EventMedia
from aidetector.application.ports import DeliveryError
from aidetector.configuration import QuietHours, TelegramConfig
from aidetector.domain.models import EventResult


def _caption(result: EventResult) -> str:
    validated = result.validation.validated
    status = " ✅" if validated is True else " ❌" if validated is False else ""
    return f"{result.event.best.score:.0%}{status}\n{round(result.event.duration)} second(s)"


def _review_buttons(result: EventResult) -> str:
    return json.dumps(
        {
            "inline_keyboard": [
                [
                    {
                        "text": "👍",
                        "callback_data": f"review:{result.id}:approved",
                    },
                    {
                        "text": "👎",
                        "callback_data": f"review:{result.id}:rejected",
                    },
                ]
            ]
        }
    )


def _is_quiet(hours: QuietHours | None, now: time) -> bool:
    if hours is None:
        return False
    start, end = time.fromisoformat(hours.start), time.fromisoformat(hours.end)
    if start <= end:
        return start <= now < end
    return now >= start or now < end


class TelegramExporter:
    def __init__(
        self,
        config: TelegramConfig,
        media: EventMedia,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.config = config
        self.media = media
        self._now = now
        self._attempted_alerts = 0

    def export(self, result: EventResult) -> None:
        try:
            attachments = self.media.attachments(
                result.event, self.config, image_max=10_000_000, video_max=12_000_000
            )
        except MediaError as error:
            raise DeliveryError(str(error)) from error
        self._attempted_alerts += 1
        silent = (
            _is_quiet(self.config.quiet, self._now().time())
            or self._attempted_alerts % self.config.alert_every != 0
        )
        fields: dict[str, object] = {
            "chat_id": self.config.chat,
            "disable_notification": "true" if silent else "false",
        }
        caption = _caption(result)
        files = {}
        if not attachments:
            method = "sendMessage"
            fields["text"] = caption
        elif len(attachments) == 1:
            attachment = attachments[0]
            kind = "video" if attachment.content_type == "video/mp4" else "photo"
            method = "sendVideo" if kind == "video" else "sendPhoto"
            fields["caption"] = caption
            files[kind] = (
                attachment.filename,
                attachment.content,
                attachment.content_type,
            )
        else:
            method = "sendMediaGroup"
            media: list[dict[str, str]] = [
                {
                    "type": "video" if item.content_type == "video/mp4" else "photo",
                    "media": f"attach://{item.name}",
                }
                for item in attachments
            ]
            media[0]["caption"] = caption
            fields["media"] = json.dumps(media)
            files = {
                item.name: (item.filename, item.content, item.content_type)
                for item in attachments
            }
        if method != "sendMediaGroup":
            fields["reply_markup"] = _review_buttons(result)
        sent = self._send(method, fields, files)
        if method == "sendMediaGroup":
            # Telegram albums cannot carry buttons; reply to the album instead.
            try:
                message_id = sent[0]["message_id"]
            except (KeyError, IndexError, TypeError) as error:
                raise DeliveryError(
                    "Telegram returned an invalid album response"
                ) from error
            self._send(
                "sendMessage",
                {
                    "chat_id": self.config.chat,
                    "text": "Is this detection correct?",
                    "disable_notification": "true",
                    "reply_parameters": json.dumps({"message_id": message_id}),
                    "reply_markup": _review_buttons(result),
                },
                {},
            )

    def _send(self, method: str, fields: dict[str, object], files: Files):
        response = send_request(
            "POST",
            f"https://api.telegram.org/bot{self.config.token}/{method}",
            timeout=self.config.timeout,
            data=fields,
            files=files,
        )
        try:
            body = response.json()
            accepted = body["ok"]
        except (ValueError, KeyError, TypeError) as error:
            raise DeliveryError("Telegram returned an invalid response") from error
        if accepted is not True:
            raise DeliveryError("Telegram did not accept the message")
        return body.get("result")
