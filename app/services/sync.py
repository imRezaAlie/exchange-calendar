"""Synchronization decisions that can be tested without a GUI thread."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.calendar.date_utils import resolve_timezone, sync_window
from app.calendar.demo_data import DEMO_MAILBOX, build_demo_meetings
from app.config import AppConfig
from app.exchange.client import ExchangeClient
from app.exchange.errors import ExchangeAuthError, ExchangeConfigError, ExchangeError
from app.models import SyncSnapshot
from app.storage.cache import CalendarCache

log = logging.getLogger(__name__)

NOT_CONFIGURED = (
    "Exchange is not configured. Open Settings to enter the server connection, "
    "or start with: python main.py --demo"
)


class SingleFlight:
    """Prevent two calendar refreshes from running at the same time."""

    def __init__(self) -> None:
        self.busy = False

    def try_acquire(self) -> bool:
        if self.busy:
            return False
        self.busy = True
        return True

    def release(self) -> None:
        self.busy = False


@dataclass(slots=True)
class SyncRequest:
    config: AppConfig
    password: str
    demo: bool
    anchor: datetime

    def __repr__(self) -> str:
        return (
            f"SyncRequest(demo={self.demo}, email={self.config.email!r}, "
            f"auth={self.config.auth_method!r})"
        )


def _ready(config: AppConfig, password: str) -> bool:
    if not config.email:
        return False
    if not config.use_autodiscover and not config.ews_url:
        return False
    if config.auth_method == "kerberos":
        return bool(config.username or config.email)
    return bool(password)


def _from_cache(cache: CalendarCache, mailbox: str, error: str, demo: bool = False) -> SyncSnapshot | None:
    cached = cache.load(mailbox)
    if cached is None or not cached.meetings:
        return None
    return SyncSnapshot(
        meetings=cached.meetings,
        tasks=cached.tasks,
        tasks_state=cached.tasks_state,
        tasks_message=cached.tasks_message or "Showing cached tasks.",
        connected=False,
        from_cache=True,
        synced_at=cached.synced_at,
        error=error,
        mailbox=mailbox,
        demo=demo,
        window_start=cached.window_start,
        window_end=cached.window_end,
    )


def _empty(mailbox: str, error: str, demo: bool = False) -> SyncSnapshot:
    return SyncSnapshot(
        meetings=[],
        tasks=[],
        tasks_state="not_configured",
        tasks_message="Not configured",
        connected=False,
        from_cache=False,
        synced_at=None,
        error=error,
        mailbox=mailbox,
        demo=demo,
    )


def perform_sync(
    request: SyncRequest,
    cache: CalendarCache,
    client_factory=ExchangeClient,
) -> SyncSnapshot:
    config = request.config
    tz = resolve_timezone(config.timezone)
    anchor = request.anchor.astimezone(tz).date()
    window_start, window_end = sync_window(anchor, tz)
    if request.demo:
        now = datetime.now(tz)
        meetings = build_demo_meetings(now.date(), tz)
        cache.save_success(
            DEMO_MAILBOX,
            meetings,
            [],
            "not_configured",
            "",
            window_start,
            window_end,
            now,
            config.cache_retention_days,
        )
        return SyncSnapshot(
            meetings=meetings,
            tasks=[],
            tasks_state="not_configured",
            tasks_message="",
            connected=True,
            from_cache=False,
            synced_at=now,
            error=None,
            mailbox=DEMO_MAILBOX,
            demo=True,
            window_start=window_start,
            window_end=window_end,
        )

    mailbox = config.email
    if not _ready(config, request.password):
        cached = _from_cache(cache, mailbox, NOT_CONFIGURED) if mailbox else None
        return cached or _empty(mailbox, NOT_CONFIGURED)

    try:
        client = client_factory(config, request.password)
        meetings = client.fetch(window_start, window_end, tz)
        synced_at = datetime.now(timezone.utc)
        cache.save_success(
            mailbox,
            meetings,
            [],
            "not_configured",
            "",
            window_start,
            window_end,
            synced_at,
            config.cache_retention_days,
        )
        log.info("Calendar sync completed for %s (%s meetings).", mailbox, len(meetings))
        return SyncSnapshot(
            meetings=meetings,
            tasks=[],
            tasks_state="not_configured",
            tasks_message="",
            connected=True,
            from_cache=False,
            synced_at=synced_at,
            error=None,
            mailbox=mailbox,
            demo=False,
            window_start=window_start,
            window_end=window_end,
        )
    except ExchangeAuthError as exc:
        log.warning("Exchange authentication failed.")
        message = str(exc)
    except ExchangeConfigError as exc:
        log.warning("Exchange settings were rejected.")
        message = str(exc)
    except ExchangeError as exc:
        log.warning("Exchange sync failed: %s", exc.__class__.__name__)
        message = str(exc)
    except Exception as exc:
        log.exception("Unexpected calendar sync failure.")
        message = f"Calendar sync failed ({exc.__class__.__name__}). Cached meetings stay visible when available."

    cached = _from_cache(cache, mailbox, message)
    if cached is not None:
        log.info("Showing the cached calendar because Exchange is unavailable.")
        return cached
    return _empty(mailbox, message)
