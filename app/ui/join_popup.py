"""Small on-top reminder with a Join action. It is not a tray icon."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.colors import colors
from app.ui.icons import bell_icon
from app.ui.widgets import make_button
from zoneinfo import ZoneInfo

from app.calendar.date_utils import as_utc
from app.calendar.links import meeting_url
from app.models import Meeting
from app.ui.meeting_details import _open_http_url


class JoinPopup(QDialog):
    def __init__(
        self,
        meeting: Meeting,
        tz: ZoneInfo,
        now: datetime,
        on_open,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.meeting = meeting
        self._on_open = on_open
        self.setWindowTitle("Meeting starting")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setObjectName("joinPopup")
        self.setFixedWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        bell = QLabel()
        bell.setPixmap(bell_icon(16, colors()["text"]).pixmap(16, 16))
        bell.setFixedSize(16, 16)
        kicker = QLabel("Meeting Reminder")
        kicker.setObjectName("sectionTitle")
        heading.addWidget(bell)
        heading.addWidget(kicker, 1)
        layout.addLayout(heading)
        subject = QLabel((meeting.subject or "").strip() or "(No subject)")
        subject.setObjectName("dialogTitle")
        subject.setWordWrap(True)
        layout.addWidget(subject)

        when = QLabel(_when_text(meeting, tz, now))
        when.setObjectName("dialogSubtitle")
        when.setWordWrap(True)
        layout.addWidget(when)

        organizer = (meeting.organizer_name or meeting.organizer_email or "").strip()
        if organizer:
            who = QLabel(f"Organizer: {organizer}")
            who.setObjectName("hintLabel")
            who.setWordWrap(True)
            layout.addWidget(who)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        dismiss = make_button("Dismiss", "secondary")
        dismiss.setFixedWidth(96)
        dismiss.clicked.connect(self.close)
        buttons.addWidget(dismiss)
        url = _join_url(meeting)
        if url.startswith("http://") or url.startswith("https://"):
            join = make_button("Join Meeting", "primary")
            join.setFixedWidth(136)
            join.clicked.connect(self._join)
            buttons.addWidget(join)
        else:
            open_details = make_button("Open", "primary")
            open_details.setFixedWidth(96)
            open_details.clicked.connect(self._open_details)
            buttons.addWidget(open_details)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

    def _join(self) -> None:
        url = _join_url(self.meeting)
        if url:
            _open_http_url(url)
        self.close()

    def _open_details(self) -> None:
        self._on_open(self.meeting)
        self.close()


def _join_url(meeting: Meeting) -> str:
    return meeting_url(meeting)


def _when_text(meeting: Meeting, tz: ZoneInfo, now: datetime) -> str:
    start = as_utc(meeting.start).astimezone(tz)
    remaining = int((as_utc(meeting.start) - as_utc(now)).total_seconds() // 60)
    clock = start.strftime("%H:%M")
    if remaining <= 0:
        return f"{clock} · Starting now"
    if remaining == 1:
        return f"{clock} · Starts in 1 minute"
    return f"{clock} · Starts in {remaining} minutes"
