import base64

from aidetector.adapters.http import send_request
from aidetector.adapters.media import MediaError
from aidetector.adapters.media.event_media import EventMedia
from aidetector.application.ports import DeliveryError
from aidetector.configuration import WebhookConfig
from aidetector.domain.models import EventResult


class WebhookExporter:
    def __init__(self, config: WebhookConfig, media: EventMedia):
        self.config = config
        self.media = media

    def export(self, result: EventResult) -> None:
        headers = dict(self.config.headers or {})
        if self.config.token is not None:
            headers["Authorization"] = self.config.token
        if self.config.body is not None or self.config.data_type == "none":
            send_request(
                self.config.method,
                self.config.url,
                timeout=self.config.timeout,
                headers=headers,
                data=self.config.body,
            )
            return

        event = result.event
        payload: dict[str, object] = {
            "confidence": event.best.score,
            "timestamp": event.best.date.isoformat(),
            "duration": event.duration,
            "validated": result.validation.validated,
        }
        try:
            attachments = self.media.attachments(
                event,
                self.config,
                image_max=self.config.data_max,
                video_max=self.config.data_max,
            )
        except MediaError as error:
            raise DeliveryError(str(error)) from error
        if self.config.data_type == "base64":
            payload.update(
                (item.name, base64.b64encode(item.content).decode("ascii"))
                for item in attachments
            )
            send_request(
                self.config.method,
                self.config.url,
                timeout=self.config.timeout,
                headers=headers,
                json_body=payload,
            )
        else:
            send_request(
                self.config.method,
                self.config.url,
                timeout=self.config.timeout,
                headers=headers,
                data=payload,
                files={
                    item.name: (item.filename, item.content, item.content_type)
                    for item in attachments
                },
            )
