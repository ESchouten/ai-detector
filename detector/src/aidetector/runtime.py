import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import ExitStack, closing
from dataclasses import dataclass
from queue import Full, Queue
from threading import Event, Thread, current_thread

from aidetector.application.delivery import DeliveryReport, EventDelivery
from aidetector.application.pipeline import DetectionPipeline
from aidetector.application.ports import FrameSource, HealthMonitor
from aidetector.domain.models import DetectionEvent, ValidationStatus

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    events: int = 0
    skipped: int = 0
    delivery_failures: int = 0
    validation_failures: int = 0

    @property
    def failed(self) -> bool:
        return self.delivery_failures > 0 or self.validation_failures > 0

    def record(self, report: DeliveryReport) -> None:
        if report.result is None:
            self.skipped += 1
            return
        self.events += 1
        self.delivery_failures += len(report.failures)
        if report.result.validation.status is ValidationStatus.FAILED:
            self.validation_failures += 1


class DetectorWorker:
    """Assemble events here and deliver them in order on one separate thread.

    The bounded queue transfers completed events to delivery. Shutdown flushes
    eligible windows and joins delivery before the worker returns its statistics.
    """

    def __init__(
        self,
        source: FrameSource,
        pipeline: DetectionPipeline,
        delivery: EventDelivery,
        pending_events: int = 8,
        *,
        name: str = "detector",
    ):
        self.name = name
        self.source = source
        self.pipeline = pipeline
        self.delivery = delivery
        self.stats = RunStats()
        self._stop = Event()
        self._queue: Queue[DetectionEvent | None] = Queue(maxsize=pending_events)
        self._delivery_error: Exception | None = None

    def run(self) -> RunStats:
        processing_thread = current_thread()
        previous_name = processing_thread.name
        delivery_thread = Thread(target=self._deliver, name=f"{self.name}-delivery")
        try:
            processing_thread.name = f"{self.name}-processing"
            logger.info("Monitoring started")
            delivery_thread.start()
            with ExitStack() as cleanup:
                # Cleanup closes the batch generator, closes input, then flushes
                # and joins delivery. ExitStack runs these registrations in reverse.
                cleanup.callback(self._finish_delivery, delivery_thread)
                cleanup.callback(self.source.close)
                batches = cleanup.enter_context(closing(self.source.batches()))
                for batch in batches:
                    if self._stop.is_set():
                        break
                    for event in self.pipeline.process(batch):
                        self._enqueue(event)
                        # The queue owns this event while the producer waits for input.
                        del event
        except Exception:
            # The supervisor propagates the first failure; concurrent failures
            # still need their own diagnostic before their futures are discarded.
            logger.exception("Detector worker failed")
            raise
        finally:
            processing_thread.name = previous_name
        return self.stats

    def stop(self) -> None:
        self._stop.set()
        self.source.close()

    def _finish_delivery(self, thread: Thread) -> None:
        try:
            if self._delivery_error is None:
                for event in self.pipeline.finish():
                    self._enqueue(event)
        finally:
            try:
                if self._delivery_error is None:
                    self._enqueue(None)
            finally:
                thread.join()
        if self._delivery_error is not None:
            raise self._delivery_error

    def _enqueue(self, event: DetectionEvent | None) -> None:
        while True:
            if self._delivery_error is not None:
                raise self._delivery_error
            try:
                self._queue.put(event, timeout=0.1)
                return
            except Full:
                continue

    def _deliver(self) -> None:
        try:
            while (event := self._queue.get()) is not None:
                self.stats.record(self.delivery.deliver(event))
                # Do not retain a completed clip during the next blocking get().
                del event
        except Exception as error:
            self._delivery_error = error
            self._stop.set()
            try:
                self.source.close()
            except Exception:
                logger.exception("Source cleanup failed after delivery worker failure")


def run_detectors(
    workers: tuple[DetectorWorker, ...],
    health: HealthMonitor | None = None,
    stop_requested: Event | None = None,
) -> tuple[RunStats, ...]:
    with ThreadPoolExecutor(
        max_workers=len(workers) + 2, thread_name_prefix="application"
    ) as pool:
        with ExitStack() as stopping:
            for worker in workers:
                stopping.callback(worker.stop)
            pending_detectors = {pool.submit(worker.run) for worker in workers}
            futures: set[Future[RunStats] | Future[None] | Future[bool]] = set(
                pending_detectors
            )
            stop_future = None
            if stop_requested is not None:
                stopping.callback(stop_requested.set)
                stop_future = pool.submit(stop_requested.wait)
                futures.add(stop_future)
            if health is not None:
                stopping.callback(health.stop)
                futures.add(pool.submit(health.run))
            try:
                for future in as_completed(futures):
                    future.result()
                    if future is stop_future:
                        logger.info(
                            "Shutdown requested by launcher; draining accepted events"
                        )
                        break
                    pending_detectors.discard(future)
                    if not pending_detectors:
                        break
            except KeyboardInterrupt:
                logger.info("Shutdown requested; draining accepted events")
        # Observe drain failures after signalling every task, including health.
        for future in futures:
            future.result()
        return tuple(worker.stats for worker in workers)
