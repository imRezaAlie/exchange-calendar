"""Background calendar synchronization. Network work stays off the GUI thread."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from app.models import SyncSnapshot
from app.services.sync import SingleFlight, SyncRequest, perform_sync
from app.storage.cache import CalendarCache

log = logging.getLogger(__name__)


class SyncWorker(QThread):
    completed = Signal(int, object)

    def __init__(self, request: SyncRequest, cache: CalendarCache, generation: int) -> None:
        super().__init__()
        self.request = request
        self.cache = cache
        self.generation = generation

    def run(self) -> None:
        try:
            snapshot = perform_sync(self.request, self.cache)
        except Exception as exc:
            log.exception("Calendar sync stopped unexpectedly.")
            snapshot = SyncSnapshot(
                meetings=[],
                tasks=[],
                tasks_state="not_configured",
                tasks_message="Not configured",
                connected=False,
                from_cache=False,
                synced_at=None,
                error=f"Calendar sync failed ({exc.__class__.__name__}).",
                mailbox=self.request.config.email,
                demo=self.request.demo,
            )
        self.completed.emit(self.generation, snapshot)


class RefreshService(QObject):
    snapshot_ready = Signal(object)
    busy_changed = Signal(bool)
    refresh_skipped = Signal()

    def __init__(self, cache: CalendarCache, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self._flight = SingleFlight()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_now)
        self._worker: SyncWorker | None = None
        self._generation = 0
        self._request_factory = None

    def set_request_factory(self, factory) -> None:
        self._request_factory = factory

    def apply_timer(self, enabled: bool, interval_minutes: int) -> None:
        self._timer.stop()
        if enabled:
            self._timer.setInterval(int(interval_minutes) * 60 * 1000)
            self._timer.start()

    def next_refresh_at(self) -> datetime | None:
        if not self._timer.isActive():
            return None
        remaining = self._timer.remainingTime()
        if remaining < 0:
            return None
        return datetime.now().astimezone() + timedelta(milliseconds=remaining)

    def refresh_now(self) -> None:
        if self._request_factory is None:
            return
        if not self._flight.try_acquire():
            self.refresh_skipped.emit()
            return
        try:
            request = self._request_factory()
        except Exception:
            self._flight.release()
            log.exception("Could not start a calendar refresh.")
            return
        self._generation += 1
        worker = SyncWorker(request, self.cache, self._generation)
        worker.completed.connect(self._on_completed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        self.busy_changed.emit(True)
        worker.start()

    def _on_completed(self, generation: int, snapshot: object) -> None:
        if generation != self._generation:
            return
        self.snapshot_ready.emit(snapshot)

    def _on_finished(self) -> None:
        self._flight.release()
        self.busy_changed.emit(False)
        self._worker = None

    def shutdown(self) -> None:
        self._timer.stop()
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        try:
            if worker.isRunning():
                worker.wait(3000)
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(1000)
        except RuntimeError:
            return
