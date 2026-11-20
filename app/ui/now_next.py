"""Now and next cards above the agenda."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.ui.widgets import make_button
from zoneinfo import ZoneInfo

from app.calendar.agenda import starts_text, until_text
from app.calendar.links import meeting_url
from app.calendar.workday import open_time_summary
from app.models import Meeting
from app.ui.meeting_details import _open_http_url


class NowNextBar(QWidget):
    open_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("nowNextBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 8)
        layout.setSpacing(4)
        self._now = _Line("Now", "now")
        self._next = _Line("Next", "next")
        self._open = _Note("Open", "open")
        self._later = _Note("Later", "later")
        self._now.open_requested.connect(self.open_requested.emit)
        self._next.open_requested.connect(self.open_requested.emit)
        layout.addWidget(self._now)
        layout.addWidget(self._next)
        layout.addWidget(self._open)
        layout.addWidget(self._later)

    @property
    def now_subject(self) -> QLabel:
        return self._now.subject

    @property
    def next_subject(self) -> QLabel:
        return self._next.subject

    @property
    def now_when(self) -> QLabel:
        return self._now.when

    @property
    def next_when(self) -> QLabel:
        return self._next.when

    @property
    def now_join(self) -> QPushButton:
        return self._now.join

    @property
    def next_join(self) -> QPushButton:
        return self._next.join

    @property
    def open_text(self) -> QLabel:
        return self._open.subject

    @property
    def later_text(self) -> QLabel:
        return self._later.subject

    def show_agenda(
        self,
        current: Meeting | None,
        upcoming: Meeting | None,
        now: datetime,
        tz: ZoneInfo,
    ) -> None:
        if current is None and upcoming is None:
            self._now.show_idle("No upcoming meetings", "")
            self._next.show_idle("Nothing else scheduled", "")
            self._next.hide()
            self._now.show()
            return
        self._now.show()
        if current is None:
            free_until = until_text(upcoming.start, now, tz) if upcoming is not None else ""
            self._now.show_idle("Free", free_until)
        else:
            self._now.show_meeting(current, until_text(current.end, now, tz))
        if upcoming is None:
            self._next.show_idle("Nothing else scheduled", "")
            self._next.hide()
        else:
            self._next.show_meeting(upcoming, starts_text(upcoming.start, now, tz))
            self._next.show()

    def show_openings(self, meetings: list[Meeting], now: datetime, week_starts_on: str) -> None:
        today_text, later_text = open_time_summary(meetings, now, week_starts_on)
        self._open.show_text(today_text)
        if later_text:
            self._later.show_text(later_text)
            self._later.show()
        else:
            self._later.hide()


class _Note(QWidget):
    def __init__(self, mark: str, name: str) -> None:
        super().__init__()
        self.setObjectName("openRow" if name == "open" else "laterRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(28)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(8)
        label = QLabel(mark)
        label.setObjectName("openMark" if name == "open" else "laterMark")
        label.setFixedWidth(58)
        self.subject = QLabel()
        self.subject.setObjectName("openSubject" if name == "open" else "laterSubject")
        self.subject.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(label)
        layout.addWidget(self.subject, 1)

    def show_text(self, text: str) -> None:
        self.subject.setText(text)
        self.subject.setToolTip(text)


class _Line(QWidget):
    open_requested = Signal(object)

    def __init__(self, mark: str, name: str) -> None:
        super().__init__()
        self._meeting: Meeting | None = None
        self.setObjectName("nowRow" if name == "now" else "nextRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(8)
        label = QLabel(mark)
        label.setObjectName("nowMark" if name == "now" else "nextMark")
        label.setFixedWidth(58)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.subject = QLabel()
        self.subject.setObjectName("nowSubject" if name == "now" else "nextSubject")
        self.subject.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.subject.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.when = QLabel()
        self.when.setObjectName("nowWhen" if name == "now" else "nextWhen")
        self.when.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.join = make_button("Join", "primary")
        self.join.setFixedWidth(88)
        self.join.clicked.connect(self._join)
        self._slot = QWidget()
        self._slot.setFixedWidth(80)
        slot_layout = QHBoxLayout(self._slot)
        slot_layout.setContentsMargins(8, 0, 0, 0)
        slot_layout.addWidget(self.join, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(label)
        layout.addWidget(self.subject, 1)
        layout.addWidget(self.when)
        layout.addWidget(self._slot)

    def show_meeting(self, meeting: Meeting, when: str) -> None:
        self._meeting = meeting
        subject = meeting.subject or "Meeting"
        self.subject.setText(subject)
        self.subject.setToolTip(subject)
        self.when.setText(when)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        url = meeting_url(meeting)
        self.join.setVisible(bool(url))
        self._slot.setVisible(bool(url))
        self.join.setToolTip(url)

    def show_idle(self, subject: str, when: str) -> None:
        self._meeting = None
        self.subject.setText(subject)
        self.subject.setToolTip("")
        self.when.setText(when)
        self.join.hide()
        self._slot.hide()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if self._meeting is None:
            return
        if self._slot.geometry().contains(event.position().toPoint()):
            return
        self.open_requested.emit(self._meeting)

    def _join(self) -> None:
        if self._meeting is None:
            return
        url = meeting_url(self._meeting)
        if url:
            _open_http_url(url)
