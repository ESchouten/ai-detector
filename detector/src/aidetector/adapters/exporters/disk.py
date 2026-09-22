import errno
import re
import tempfile
from datetime import timedelta
from pathlib import Path

from aidetector.adapters.exporters.archive_metadata import EventMetadata
from aidetector.adapters.media import MediaError
from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.media.images import encode_jpeg
from aidetector.application.ports import DeliveryError
from aidetector.configuration import DiskConfig
from aidetector.domain.models import EventResult, ValidationStatus


def _publish_event(pending: Path, destination: Path, result: EventResult) -> None:
    """Publish a complete archive, choosing the next timestamp on collision."""
    event_time = result.event.best.date
    while True:
        timestamp = event_time.isoformat(timespec="microseconds").replace(":", "-")
        target = destination / timestamp
        metadata = EventMetadata.from_result(result, timestamp)
        (pending / "metadata.json").write_text(
            metadata.model_dump_json(), encoding="utf-8"
        )
        if not target.exists():
            try:
                pending.rename(target)
                return
            except OSError as error:
                if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
        event_time += timedelta(microseconds=1)


class DiskExporter:
    def __init__(self, config: DiskConfig, root: Path, media: EventMedia):
        self.config = config
        self.root = root
        self.media = media

    def export(self, result: EventResult) -> None:
        try:
            self._write_event(result)
        except (OSError, MediaError) as error:
            raise DeliveryError(f"Cannot archive event: {error}") from error

    def _write_event(self, result: EventResult) -> None:
        event = result.event
        best = event.best
        if self.config.directory is not None:
            category = self.config.directory
        else:
            label = max(
                best.confidence, key=best.confidence.__getitem__, default="unclassified"
            )
            category = re.sub(r"[^\w .-]", "_", label).strip(" .") or "unclassified"
        status = result.validation.status
        stage = "unvalidated" if status is ValidationStatus.FAILED else status.value
        destination = self.root / category / stage
        staging = self.root / category / ".pending"
        destination.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="event-", dir=staging) as directory:
            pending = Path(directory)
            if self.config.strategy == "ALL":
                for index, observation in enumerate(event.observations):
                    timestamp = observation.date.isoformat(
                        timespec="microseconds"
                    ).replace(":", "-")
                    (pending / f"{timestamp}_{index}.jpg").write_bytes(
                        encode_jpeg(observation.image)
                    )
            for kind, filename in (
                ("annotated", "best.jpg"),
                ("original", "clean.jpg"),
            ):
                (pending / filename).write_bytes(self.media.image(event, kind))
            (pending / "video.mp4").write_bytes(
                self.media.video(event, padding=self.config.crop_padding)
            )

            # Whole directories are published atomically, so readers never see
            # an event whose metadata or video is still being written.
            _publish_event(pending, destination, result)
