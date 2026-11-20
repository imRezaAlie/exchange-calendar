"""SQLite cache of the last successful calendar synchronization.

Passwords are not stored. The database file is restricted to the current user,
and each mailbox is isolated from the others.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import Meeting, TaskItem, from_utc_iso, to_utc_iso

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CachedCalendar:
    meetings: list[Meeting]
    tasks: list[TaskItem]
    tasks_state: str
    tasks_message: str
    synced_at: datetime | None
    window_start: datetime | None
    window_end: datetime | None


class CalendarCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._secure()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    mailbox TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    start_utc TEXT NOT NULL,
                    end_utc TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (mailbox, uid)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    mailbox TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (mailbox, uid)
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    mailbox TEXT PRIMARY KEY,
                    synced_at TEXT,
                    window_start TEXT,
                    window_end TEXT,
                    tasks_state TEXT,
                    tasks_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_meetings_window
                    ON meetings (mailbox, start_utc, end_utc);
                """
            )
        self._secure()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _secure(self) -> None:
        try:
            os.chmod(self.path.parent, 0o700)
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except OSError:
            log.warning("Could not restrict calendar cache permissions.")

    def save_success(
        self,
        mailbox: str,
        meetings: list[Meeting],
        tasks: list[TaskItem],
        tasks_state: str,
        tasks_message: str,
        window_start: datetime,
        window_end: datetime,
        synced_at: datetime,
        retention_days: int,
    ) -> None:
        if not mailbox:
            return
        start_key = to_utc_iso(window_start)
        end_key = to_utc_iso(window_end)
        synced_key = to_utc_iso(synced_at)
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM meetings
                WHERE mailbox = ? AND start_utc < ? AND end_utc > ?
                """,
                (mailbox, end_key, start_key),
            )
            for meeting in meetings:
                meeting.mailbox = mailbox
                connection.execute(
                    """
                    INSERT INTO meetings (mailbox, uid, start_utc, end_utc, payload)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(mailbox, uid) DO UPDATE SET
                        start_utc = excluded.start_utc,
                        end_utc = excluded.end_utc,
                        payload = excluded.payload
                    """,
                    (
                        mailbox,
                        meeting.uid,
                        to_utc_iso(meeting.start),
                        to_utc_iso(meeting.end),
                        json.dumps(meeting.to_dict(), ensure_ascii=False),
                    ),
                )
            cutoff = to_utc_iso(datetime.now(timezone.utc) - timedelta(days=retention_days))
            horizon = to_utc_iso(datetime.now(timezone.utc) + timedelta(days=retention_days * 2))
            connection.execute(
                "DELETE FROM meetings WHERE mailbox = ? AND end_utc < ?",
                (mailbox, cutoff),
            )
            connection.execute(
                "DELETE FROM meetings WHERE mailbox = ? AND start_utc > ?",
                (mailbox, horizon),
            )
            if tasks_state in {"ok", "not_configured"}:
                connection.execute("DELETE FROM tasks WHERE mailbox = ?", (mailbox,))
                if tasks_state == "ok":
                    for task in tasks:
                        task.mailbox = mailbox
                        connection.execute(
                            """
                            INSERT INTO tasks (mailbox, uid, payload)
                            VALUES (?, ?, ?)
                            """,
                            (mailbox, task.uid, json.dumps(task.to_dict(), ensure_ascii=False)),
                        )
            connection.execute(
                """
                INSERT INTO sync_state
                    (mailbox, synced_at, window_start, window_end, tasks_state, tasks_message)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mailbox) DO UPDATE SET
                    synced_at = excluded.synced_at,
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    tasks_state = excluded.tasks_state,
                    tasks_message = excluded.tasks_message
                """,
                (mailbox, synced_key, start_key, end_key, tasks_state, tasks_message),
            )
        self._secure()

    def load(self, mailbox: str) -> CachedCalendar | None:
        if not mailbox:
            return None
        with self._connect() as connection:
            state = connection.execute(
                "SELECT * FROM sync_state WHERE mailbox = ?",
                (mailbox,),
            ).fetchone()
            meeting_rows = connection.execute(
                "SELECT payload FROM meetings WHERE mailbox = ? ORDER BY start_utc, uid",
                (mailbox,),
            ).fetchall()
            task_rows = connection.execute(
                "SELECT payload FROM tasks WHERE mailbox = ? ORDER BY uid",
                (mailbox,),
            ).fetchall()
        if state is None and not meeting_rows:
            return None
        meetings = [Meeting.from_dict(json.loads(row["payload"])) for row in meeting_rows]
        tasks = [TaskItem.from_dict(json.loads(row["payload"])) for row in task_rows]
        return CachedCalendar(
            meetings=meetings,
            tasks=tasks,
            tasks_state=(state["tasks_state"] if state else "not_configured") or "not_configured",
            tasks_message=(state["tasks_message"] if state else "") or "",
            synced_at=from_utc_iso(state["synced_at"]) if state else None,
            window_start=from_utc_iso(state["window_start"]) if state else None,
            window_end=from_utc_iso(state["window_end"]) if state else None,
        )
