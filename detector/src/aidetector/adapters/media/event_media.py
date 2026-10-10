from dataclasses import dataclass, replace
from typing import Literal, overload
from weakref import ReferenceType, ref

from aidetector.adapters.media.images import (
    compress_jpeg,
    crop_observation,
    draw_boxes,
    encode_jpeg,
)
from aidetector.adapters.media.video import encode_video
from aidetector.configuration import MediaConfig
from aidetector.domain.models import DetectionEvent

ImageKind = Literal["original", "annotated", "crop"]


@dataclass(frozen=True)
class _ImageKey:
    kind: ImageKind
    max_bytes: int | None
    crop_padding: float | None
    annotate_crop: bool | None


@dataclass(frozen=True)
class _VideoKey:
    width: int | None
    crf: int
    padding: float
    plot: bool
    max_bytes: int | None


@dataclass(frozen=True)
class Attachment:
    name: str
    filename: str
    content: bytes
    content_type: str


class EventMedia:
    """Cache requested encodings for one event in an ordered delivery worker."""

    def __init__(self):
        self._event: ReferenceType[DetectionEvent] | None = None
        self._images: dict[_ImageKey, bytes | None] = {}
        self._videos: dict[_VideoKey, bytes] = {}

    def _use(self, event: DetectionEvent) -> None:
        if self._event is None or self._event() is not event:
            images, videos = self._images, self._videos

            def clear_encodings(_: object = None) -> None:
                images.clear()
                videos.clear()

            clear_encodings()
            # Encodings live with the event; the cache never owns its raw frames.
            self._event = ref(event, clear_encodings)

    @overload
    def image(
        self,
        event: DetectionEvent,
        kind: Literal["original", "annotated"],
        padding: float = 0.1,
        data_max: int | None = None,
        plot_crop: bool = True,
    ) -> bytes: ...

    @overload
    def image(
        self,
        event: DetectionEvent,
        kind: Literal["crop"],
        padding: float = 0.1,
        data_max: int | None = None,
        plot_crop: bool = True,
    ) -> bytes | None: ...

    def image(
        self,
        event: DetectionEvent,
        kind: ImageKind,
        padding: float = 0.1,
        data_max: int | None = None,
        plot_crop: bool = True,
    ) -> bytes | None:
        self._use(event)
        key = _ImageKey(
            kind,
            data_max,
            crop_padding=padding if kind == "crop" else None,
            annotate_crop=plot_crop if kind == "crop" else None,
        )
        if key not in self._images:
            best = event.best
            if kind == "original":
                image = best.image
            elif kind == "annotated":
                image = draw_boxes(best)
            else:
                image = crop_observation(best, padding=padding, plot=plot_crop)
            if image is None:
                self._images[key] = None
            elif data_max is None:
                self._images[key] = encode_jpeg(image)
            else:
                self._images[key] = compress_jpeg(image, data_max)
        return self._images[key]

    def video(
        self,
        event: DetectionEvent,
        width: int | None = 1280,
        crf: int = 28,
        padding: float = 0.1,
        data_max: int | None = None,
        plot: bool = True,
    ) -> bytes:
        self._use(event)
        key = _VideoKey(
            width=width, crf=crf, padding=padding, plot=plot, max_bytes=data_max
        )
        video = self._videos.get(key)
        unrestricted = self._videos.get(replace(key, max_bytes=None))
        if (
            video is None
            and data_max is not None
            and unrestricted is not None
            and len(unrestricted) <= data_max
        ):
            video = unrestricted
            self._videos[key] = video
        if video is None:
            video = encode_video(
                event.observations,
                width=width,
                crf=crf,
                padding=padding,
                data_max=data_max,
                plot=plot,
            )
            self._videos[key] = video
        return video

    def attachments(
        self,
        event: DetectionEvent,
        config: MediaConfig,
        *,
        image_max: int | None = None,
        video_max: int | None = None,
    ) -> list[Attachment]:
        attachments: list[Attachment] = []
        timestamp = event.best.date.isoformat(timespec="milliseconds").replace(":", "-")
        for kind, name, enabled in (
            ("original", "image", config.include_image),
            ("annotated", "photo", config.include_plot),
            ("crop", "crop", config.include_crop),
        ):
            if enabled:
                content = self.image(event, kind, config.crop_padding, image_max)
                if content is not None:
                    attachments.append(
                        Attachment(
                            name, f"{timestamp}_{name}.jpg", content, "image/jpeg"
                        )
                    )
        if config.include_video:
            content = self.video(
                event,
                width=config.video_width,
                crf=config.video_crf,
                padding=config.crop_padding,
                data_max=video_max,
            )
            attachments.append(
                Attachment("video", f"{timestamp}.mp4", content, "video/mp4")
            )
        return attachments
