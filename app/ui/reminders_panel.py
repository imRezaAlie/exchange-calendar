"""Compact list of the next meeting and task alarms."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.models import Meeting
from app.services.alarms import next_trigger
from app.storage.reminders import ReminderStore
from app.ui.colors import colors
from app.ui.icons import bell_icon
from app.ui.widgets import SectionHeader


class ReminderPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("reminderPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = SectionHeader("Reminders")
        self._status = QLabel("Off")
        self._status.setObjectName("connectionStatus")
        bell = QLabel()
        bell.setPixmap(bell_icon(16, colors()["text"]).pixmap(16, 16))
        bell.setFixedSize(16, 16)
        self._bell = bell
        self._header.add_trailing(bell)
        self._header.add_trailing(self._status)
        root.addWidget(self._header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self._body = QVBoxLayout(host)
        self._body.setContentsMargins(16, 8, 16, 12)
        self._body.setSpacing(4)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self._show_empty("Reminders are off.")

    def refresh_icons(self) -> None:
        self._bell.setPixmap(bell_icon(16, colors()["text"]).pixmap(16, 16))

    def refresh(
        self,
        meetings: list[Meeting],
        store: ReminderStore,
        config: AppConfig,
        tz: ZoneInfo,
        conflict_ids: set[str],
    ) -> None:
        self.refresh_icons()
        now = datetime.now(tz)
        if not config.reminders_enabled:
            self._set_status("Off", "quiet")
            self._show_empty("Reminders are off.")
            return
        if config.alarms_muted:
            self._set_status("Muted", "warn")
        else:
            self._set_status("On", "ok")

        upcoming = next_trigger(
            meetings,
            store.todos,
            store.snoozes,
            now,
            tz,
            list(config.meeting_reminder_offsets),
            store.fired,
        )
        lead = ""
        if upcoming is not None:
            lead = f"Next alarm {upcoming.astimezone(tz).strftime('%H:%M')}"

        rows = _upcoming(meetings, store, now, tz, conflict_ids)
        self._clear()
        if lead:
            note = QLabel(lead)
            note.setObjectName("hintLabel")
            self._body.addWidget(note)
        if not rows:
            empty = QLabel("Nothing else is scheduled to ring.")
            empty.setObjectName("hintLabel")
            self._body.addWidget(empty)
            return
        for when, kind, title, conflict in rows:
            self._body.addWidget(_row(when, kind, title, conflict))

    def _set_status(self, text: str, tone: str) -> None:
        self._status.setText(text)
        self._status.setProperty("tone", tone)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _show_empty(self, text: str) -> None:
        self._clear()
        label = QLabel(text)
        label.setObjectName("hintLabel")
        self._body.addWidget(label)

    def _clear(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()


def _row(when: datetime, kind: str, title: str, conflict: bool) -> QWidget:
    widget = QFrame()
    widget.setObjectName("reminderRow")
    widget.setFixedHeight(28)
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    clock = QLabel(when.strftime("%H:%M"))
    clock.setObjectName("reminderTime")
    clock.setFixedWidth(44)
    label = QLabel(kind)
    label.setObjectName("reminderKind")
    label.setFixedWidth(64)
    subject = QLabel(title)
    subject.setObjectName("reminderTitle")
    subject.setProperty("conflict", "true" if conflict else "false")
    if conflict:
        subject.setToolTip("This meeting conflicts with another")
    layout.addWidget(clock)
    layout.addWidget(label)
    layout.addWidget(subject, 1)
    return widget


def _upcoming(meetings, store: ReminderStore, now: datetime, tz: ZoneInfo, conflict_ids: set[str]):
    rows: list[tuple[datetime, str, str, bool]] = []
    horizon = now + timedelta(hours=18)
    for meeting in meetings:
        if meeting.is_cancelled or meeting.is_all_day:
            continue
        start = meeting.start.astimezone(tz)
        if now <= start <= horizon:
            rows.append((start, "Meeting", meeting.subject or "Meeting", meeting.uid in conflict_ids))
    for todo in store.todos:
        if todo.completed or not todo.reminder_time:
            continue
        moment = _todo_clock(todo, tz)
        if moment is not None and now <= moment <= horizon:
            rows.append((moment, "Task", todo.title or "Task", False))
    for record in store.snoozes:
        moment = _parse(record.trigger_at)
        if moment is None:
            continue
        local = moment.astimezone(tz)
        if now <= local <= horizon:
            rows.append((local, "Snoozed", record.title or "Reminder", bool(record.conflict_name)))
    rows.sort(key=lambda item: item[0])
    return rows


def _todo_clock(todo, tz: ZoneInfo) -> datetime | None:
    try:
        year, month, day = (int(part) for part in todo.scheduled_date.split("-"))
        hour, minute = (int(part) for part in todo.reminder_time.split(":", 1))
    except (TypeError, ValueError):
        return None
    return datetime(year, month, day, hour, minute, tzinfo=tz)


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
