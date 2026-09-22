import logging
from threading import Event

from aidetector.adapters.http import send_request
from aidetector.application.ports import DeliveryError
from aidetector.configuration import HealthcheckConfig

logger = logging.getLogger(__name__)


class Healthcheck:
    def __init__(self, config: HealthcheckConfig):
        self.config = config
        self._stop = Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            self._ping_until_stopped()
        except Exception:
            logger.exception("Healthcheck worker failed")
            raise

    def _ping_until_stopped(self) -> None:
        while not self._stop.is_set():
            try:
                send_request(
                    self.config.method,
                    self.config.url,
                    timeout=self.config.timeout,
                    headers=self.config.headers,
                    data=self.config.body,
                )
            except DeliveryError as error:
                logger.warning("Healthcheck failed: %s", error)
            self._stop.wait(self.config.interval)
