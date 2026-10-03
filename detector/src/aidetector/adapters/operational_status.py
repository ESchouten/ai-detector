"""Versioned launcher protocol. Human logs remain independent of these records."""

import hashlib
import json
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import TextIO

from aidetector.application.status import StatusEvent

STATUS_PREFIX = "AIDETECTOR_STATUS "


def source_key(source: str) -> str:
    """Stable identity for launcher records and human diagnostics."""
    return hashlib.sha256(source.encode()).hexdigest()


class JsonStatusReporter:
    def __init__(self, output: TextIO):
        self.output = output
        self._lock = Lock()
        self._last_sent: dict[
            tuple[str, str | None, str | None], tuple[float, str | None]
        ] = {}

    def __call__(self, event: StatusEvent) -> None:
        # Captures and delivery workers report concurrently. Keep each record
        # intact and bound per-frame traffic without delaying the first frame.
        with self._lock:
            now = monotonic()
            key = (event.kind, event.source, event.rule_id)
            if event.kind in {
                "frame",
                "inference",
                "processed",
                "waiting_delivery",
            }:
                previous = self._last_sent.get(key)
                if (
                    previous is not None
                    and now - previous[0] < 1
                    and previous[1] == event.source_epoch
                ):
                    return
                self._last_sent[key] = (now, event.source_epoch)
            record: dict[str, str | int] = {
                "version": 1,
                "event": event.kind,
                "at": datetime.now(UTC).isoformat(),
            }
            if event.source is not None:
                record["sourceKey"] = source_key(event.source)
            if event.message is not None:
                record["message"] = event.message
            if event.rule_id is not None:
                record["ruleId"] = event.rule_id
            if event.destination_id is not None:
                record["destinationId"] = event.destination_id
            if event.source_epoch is not None:
                record["sourceEpoch"] = event.source_epoch
            self.output.write(STATUS_PREFIX + json.dumps(record) + "\n")
            self.output.flush()
