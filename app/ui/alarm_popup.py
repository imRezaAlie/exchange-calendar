"""Compact alarm card. It stays up until the user snoozes or dismisses it."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.colors import colors
from app.ui.icons import bell_icon
from app.ui.widgets import make_button
from zoneinfo import ZoneInfo

from app.calendar.date_utils import as_utc
from app.services.alarms import SNOOZE_MINUTES, DueAlarm
from app.ui.meeting_details import _open_http_url


class AlarmPopup(QDialog):
    snoozed = Signal(object, int)
    dismissed = Signal(object)
    completed = Signal(object)
    details_requested = Signal(object)

    def __init__(self, alarm: DueAlarm, tz: ZoneInfo, now: datetime, snooze_enabled: bool, _parent=None) -> None:
        super().__init__(None)
        self.alarm = alarm
        self.setWindowTitle("Reminder")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(False)
        self.setObjectName("joinPopup")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        bell = QLabel()
        bell.setPixmap(bell_icon(16, colors()["text"]).pixmap(16, 16))
        bell.setFixedSize(16, 16)
        kicker = QLabel(_kicker(alarm))
        kicker.setObjectName("sectionTitle")
        heading.addWidget(bell)
        heading.addWidget(kicker, 1)
        layout.addLayout(heading)

        title = QLabel(alarm.title)
        title.setObjectName("dialogTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        when = QLabel(_when(alarm, tz, now))
        when.setObjectName("dialogSubtitle")
        when.setWordWrap(True)
        layout.addWidget(when)

        if alarm.cached:
            cached = QLabel("This meeting came from the saved calendar. Exchange was unavailable.")
            cached.setObjectName("hintLabel")
            cached.setWordWrap(True)
            layout.addWidget(cached)

        if alarm.conflict_name:
            warning = QLabel(
                f"Conflicts with {alarm.conflict_name}. Overlap: {alarm.conflict_minutes} minutes."
            )
            warning.setObjectName("errorLabel")
            warning.setWordWrap(True)
            layout.addWidget(warning)
        elif alarm.kind == "meeting" and not alarm.url and alarm.location:
            place = QLabel(alarm.location)
            place.setObjectName("hintLabel")
            place.setWordWrap(True)
            layout.addWidget(place)
        elif alarm.kind == "summary" and alarm.location:
            body = QLabel(alarm.location)
            body.setObjectName("hintLabel")
            body.setWordWrap(True)
            layout.addWidget(body)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if alarm.url.startswith("http://") or alarm.url.startswith("https://"):
            join = make_button("Join Meeting", "primary")
            join.setFixedWidth(136)
            join.clicked.connect(self._join)
            buttons.addWidget(join)
        if alarm.kind == "todo":
            done = make_button("Mark as Done", "primary")
            done.setFixedWidth(136)
            done.clicked.connect(self._complete)
            buttons.addWidget(done)
            open_task = make_button("Open Task", "secondary")
            open_task.setFixedWidth(112)
            open_task.clicked.connect(lambda _checked=False, item=alarm: self.details_requested.emit(item))
            buttons.addWidget(open_task)
        if alarm.kind == "meeting" and alarm.conflict_name:
            view = make_button("View Conflict", "secondary")
            view.setFixedWidth(128)
            view.clicked.connect(lambda _checked=False, item=alarm: self.details_requested.emit(item))
            buttons.addWidget(view)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        snooze_row = QHBoxLayout()
        snooze_row.setSpacing(8)
        self.snooze_box = QComboBox()
        for minutes in SNOOZE_MINUTES:
            self.snooze_box.addItem(f"{minutes} minutes", minutes)
        self.snooze_box.setEnabled(snooze_enabled)
        self.snooze_box.setFixedWidth(128)
        snooze = make_button("Snooze", "secondary")
        dismiss = make_button("Dismiss", "secondary")
        snooze.setFixedWidth(96)
        dismiss.setFixedWidth(96)
        snooze.setEnabled(snooze_enabled)
        snooze.clicked.connect(self._snooze)
        dismiss.clicked.connect(self._dismiss)
        snooze_row.addWidget(self.snooze_box)
        snooze_row.addStretch(1)
        snooze_row.addWidget(snooze)
        snooze_row.addWidget(dismiss)
        layout.addLayout(snooze_row)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.adjustSize()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

    def _join(self) -> None:
        _open_http_url(self.alarm.url)

    def _snooze(self) -> None:
        minutes = int(self.snooze_box.currentData())
        alarm = self.alarm
        self.snoozed.emit(alarm, minutes)
        self.close()

    def _dismiss(self) -> None:
        self.dismissed.emit(self.alarm)
        self.close()

    def _complete(self) -> None:
        self.completed.emit(self.alarm)
        self.close()


def _kicker(alarm: DueAlarm) -> str:
    if alarm.kind == "todo":
        return "TODO Reminder"
    if alarm.kind == "summary":
        return "Today's tasks"
    if alarm.conflict_name:
        return "Meeting Reminder — Conflict Detected"
    return "Meeting Reminder"


def _when(alarm: DueAlarm, tz: ZoneInfo, now: datetime) -> str:
    clock = alarm.event_at.astimezone(tz).strftime("%H:%M")
    if alarm.kind == "todo":
        priority = (alarm.priority or "normal").capitalize()
        return f"Priority: {priority} · Scheduled {clock}"
    if alarm.kind == "summary":
        return "Daily summary"
    if alarm.snoozed:
        return f"Snoozed · {clock}"
    remaining = int((as_utc(alarm.event_at) - as_utc(now)).total_seconds() // 60)
    if remaining <= 0:
        lead = "Starting now"
    elif remaining == 1:
        lead = "Starts in 1 minute"
    else:
        lead = f"Starts in {remaining} minutes"
    return f"{lead} · {clock}"
