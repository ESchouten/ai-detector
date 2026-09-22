"""Versioned launcher protocol. Human logs remain independent of these records."""

import hashlib
import json
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import TextIO

from aidetector.application.status import StatusEvent

STATUS_PREFIX = "AIDETECTOR_STATUS "


class JsonStatusReporter:
    def __init__(self, output: TextIO):
        self.output = output
        self._lock = Lock()
        self._last_sent: dict[tuple[str, str | None, str | None], float] = {}

    def __call__(self, event: StatusEvent) -> None:
        # Captures and delivery workers report concurrently. Keep each record
        # intact and bound per-frame traffic without delaying the first frame.
        with self._lock:
            now = monotonic()
            key = (event.kind, event.source, event.rule_id)
            if event.kind in {"frame", "inference", "processed", "offline"}:
                previous = self._last_sent.get(key)
                if previous is not None and now - previous < 1:
                    return
                self._last_sent[key] = now
            record: dict[str, str | int] = {
                "version": 1,
                "event": event.kind,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            if event.source is not None:
                record["sourceKey"] = hashlib.sha256(event.source.encode()).hexdigest()
            if event.message is not None:
                record["message"] = event.message
            if event.rule_id is not None:
                record["ruleId"] = event.rule_id
            if event.destination_id is not None:
                record["destinationId"] = event.destination_id
            self.output.write(STATUS_PREFIX + json.dumps(record) + "\n")
            self.output.flush()
