"""Event details and the conflict list. Both live in the side panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import ConflictReport, format_conflict_popup
from app.calendar.date_utils import format_long_date, format_minutes, format_time_span
from app.calendar.links import meeting_url, place_name
from app.models import Meeting
from app.ui.meeting_details import _BUSY, _RESPONSE, _open_http_url, _person
from app.ui.widgets import make_button


class EventDetailsPanel(QWidget):
    full_details_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._meeting: Meeting | None = None
        self._url = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self._body = QVBoxLayout(host)
        self._body.setContentsMargins(16, 16, 16, 16)
        self._body.setSpacing(8)
        self._title = QLabel("No meeting selected")
        self._title.setObjectName("dialogTitle")
        self._title.setWordWrap(True)
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._when = QLabel("Choose a meeting in the calendar to see its details.")
        self._when.setObjectName("dialogSubtitle")
        self._when.setWordWrap(True)
        self._facts = QLabel()
        self._facts.setObjectName("hintLabel")
        self._facts.setWordWrap(True)
        self._facts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._conflict = QLabel()
        self._conflict.setObjectName("hintLabel")
        self._conflict.setWordWrap(True)
        self._conflict.hide()
        self.join_button = make_button("Join meeting", "primary")
        self.join_button.clicked.connect(self._join)
        self.join_button.hide()
        self.more_button = make_button("Full details", "secondary")
        self.more_button.clicked.connect(self._more)
        self.more_button.hide()
        self._body.addWidget(self._title)
        self._body.addWidget(self._when)
        self._body.addWidget(self._facts)
        self._body.addWidget(self._conflict)
        self._body.addWidget(self.join_button)
        self._body.addWidget(self.more_button)
        self._body.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll)

    def show_meeting(
        self,
        meeting: Meeting,
        report: ConflictReport,
        meetings_by_id: dict[str, Meeting],
        tz: ZoneInfo,
    ) -> None:
        self._meeting = meeting
        subject = (meeting.subject or "").strip() or "(No subject)"
        self._title.setText(subject)
        local_start = meeting.start.astimezone(tz)
        local_end = meeting.end.astimezone(tz)
        when = "All day" if meeting.is_all_day else f"{local_start.strftime('%H:%M')}–{local_end.strftime('%H:%M')}"
        self._when.setText(f"{format_long_date(local_start.date())}  ·  {when}")
        rows = [
            ("Organizer", _person(meeting.organizer_name, meeting.organizer_email)),
            ("Location", place_name(meeting.location) or "No location"),
            ("Show as", _BUSY.get(meeting.busy_status, meeting.busy_status or "Not specified")),
            ("Your response", _RESPONSE.get(meeting.response_status, meeting.response_status or "Unknown")),
        ]
        if meeting.is_recurring:
            rows.append(("Repeats", "Recurring"))
        if meeting.is_cancelled:
            rows.append(("Status", "Cancelled"))
        attendees = len(meeting.required_attendees) + len(meeting.optional_attendees)
        if attendees:
            rows.append(("Attendees", str(attendees)))
        self._facts.setText("\n".join(f"{label}: {value}" for label, value in rows))
        self._url = meeting_url(meeting) or ""
        self.join_button.setVisible(bool(self._url))
        self.join_button.setToolTip(self._url)
        self.more_button.show()
        if report.has_conflict(meeting.uid):
            self._conflict.setText(format_conflict_popup(meeting, report, meetings_by_id, tz))
            self._conflict.show()
        else:
            self._conflict.hide()

    def clear(self) -> None:
        self._meeting = None
        self._url = ""
        self._title.setText("No meeting selected")
        self._when.setText("Choose a meeting in the calendar to see its details.")
        self._facts.clear()
        self._conflict.hide()
        self.join_button.hide()
        self.more_button.hide()

    def _join(self) -> None:
        if self._url:
            _open_http_url(self._url)

    def _more(self) -> None:
        if self._meeting is not None:
            self.full_details_requested.emit(self._meeting)


class ConflictPanel(QWidget):
    meeting_chosen = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self._body = QVBoxLayout(self._host)
        self._body.setContentsMargins(16, 16, 16, 16)
        self._body.setSpacing(12)
        self._body.addStretch(1)
        scroll.setWidget(self._host)
        root.addWidget(scroll)

    def show_report(self, meetings: list[Meeting], report: ConflictReport, tz: ZoneInfo) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        clusters: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        for meeting in meetings:
            if not report.has_conflict(meeting.uid):
                continue
            cluster = tuple(report.cluster_containing(meeting.uid))
            if not cluster or cluster in seen:
                continue
            seen.add(cluster)
            clusters.append(cluster)
        if not clusters:
            empty = QLabel("No scheduling conflicts in the loaded calendar.")
            empty.setObjectName("emptyDay")
            empty.setWordWrap(True)
            self._body.addWidget(empty)
            self._body.addStretch(1)
            return
        by_id = {meeting.uid: meeting for meeting in meetings}
        for cluster in clusters:
            card = QFrame()
            card.setObjectName("conflictCard")
            card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(4)
            names = [by_id[uid] for uid in cluster if uid in by_id]
            heading = QLabel(f"{len(names)} overlapping meetings")
            heading.setObjectName("panelHeading")
            heading.setWordWrap(True)
            layout.addWidget(heading)
            overlaps = report.overlaps_among(cluster)
            if overlaps:
                window = overlaps[0]
                note = QLabel(
                    f"Overlap {format_time_span(window.start, window.end, tz)} · {format_minutes(window.minutes)}"
                )
                note.setObjectName("hintLabel")
                note.setWordWrap(True)
                layout.addWidget(note)
            for meeting in names:
                button = make_button(meeting.subject or "(No subject)", "secondary")
                button.setToolTip("Show this meeting")
                button.clicked.connect(lambda _checked=False, item=meeting: self.meeting_chosen.emit(item))
                layout.addWidget(button)
            self._body.addWidget(card)
        self._body.addStretch(1)
