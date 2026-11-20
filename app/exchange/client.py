"""Read-only Exchange client. Calendar items are fetched; mail folders are not."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.exchange.authentication import connect_account
from app.exchange.calendar_service import fetch_meetings
from app.exchange.errors import ExchangeTransportError
from app.models import Meeting


class ExchangeClient:
    def __init__(self, config: AppConfig, password: str) -> None:
        self.config = config
        self._password = password
        self._account = None

    def __repr__(self) -> str:
        return f"ExchangeClient(email={self.config.email!r}, auth={self.config.auth_method!r})"

    def connect(self, tz: ZoneInfo) -> None:
        self._account = connect_account(self.config, self._password, tz)

    def fetch(
        self,
        start: datetime,
        end: datetime,
        tz: ZoneInfo,
    ) -> list[Meeting]:
        last_error: ExchangeTransportError | None = None
        for attempt in (1, 2):
            try:
                if self._account is None:
                    self.connect(tz)
                return fetch_meetings(self._account, start, end, self.config.email, tz)
            except ExchangeTransportError as exc:
                last_error = exc
                self._account = None
                if attempt == 1:
                    time.sleep(1)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise ExchangeTransportError("The Exchange server could not be reached.")

    def version_text(self) -> str:
        if self._account is None:
            return "Connected to Exchange."
        version = getattr(self._account, "version", None)
        if version:
            return f"Connected to Exchange ({version})."
        return "Connected to Exchange."
