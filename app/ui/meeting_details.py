"""Read-only meeting details, including the overlap window when meetings conflict."""

from __future__ import annotations

from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.calendar.conflict_detector import ConflictReport, format_conflict_popup
from app.calendar.links import meeting_url, place_name
from app.ui.colors import colors
from app.ui.theme import FONT_CSS
from app.ui.widgets import make_button
from app.calendar.date_utils import format_long_date
from app.html_text import body_to_html, html_to_text
from app.models import Attendee, Meeting

_BUSY = {
    "free": "Free",
    "tentative": "Tentative",
    "busy": "Busy",
    "oof": "Out of Office",
    "working_elsewhere": "Working Elsewhere",
    "no_data": "Not specified",
}
_RESPONSE = {
    "accepted": "Accepted",
    "declined": "Declined",
    "tentative": "Tentative",
    "not_responded": "Not responded",
    "organizer": "Organizer",
    "none": "None",
    "unknown": "Unknown",
}


def _person(name: str, email: str) -> str:
    if name and email and name.lower() != email.lower():
        return f"{name} <{email}>"
    return name or email or "Unknown"


def _attendee_line(attendee: Attendee) -> str:
    suffix = "" if attendee.required else " (optional)"
    response = _RESPONSE.get(attendee.response, attendee.response)
    extra = f" — {response}" if response and response != "Unknown" else ""
    return f"{_person(attendee.name, attendee.email)}{suffix}{extra}"


class MeetingDetailsDialog(QDialog):
    def __init__(
        self,
        meeting: Meeting,
        report: ConflictReport,
        meetings_by_id: dict[str, Meeting],
        tz: ZoneInfo,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.meeting = meeting
        self._link = _join_link(meeting)
        subject = (meeting.subject or "").strip() or "(No subject)"
        self.setWindowTitle(subject)
        self.setModal(True)
        self.resize(560, 640)
        self.setMinimumWidth(460)

        local_start = meeting.start.astimezone(tz)
        local_end = meeting.end.astimezone(tz)
        when = "All day" if meeting.is_all_day else f"{local_start.strftime('%H:%M')} – {local_end.strftime('%H:%M')}"

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(16)

        title = QLabel(subject)
        title.setObjectName("dialogTitle")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(title)
        subtitle = QLabel(f"{format_long_date(local_start.date())}   ·   {when}")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 8, 4)
        body_layout.setSpacing(14)

        facts = QWidget()
        facts_layout = QVBoxLayout(facts)
        facts_layout.setContentsMargins(0, 0, 0, 0)
        facts_layout.setSpacing(4)
        rows = [
            ("Organizer", _person(meeting.organizer_name, meeting.organizer_email)),
            ("Location", place_name(meeting.location) or "No location"),
            ("Show as", _BUSY.get(meeting.busy_status, meeting.busy_status)),
            ("Your response", _RESPONSE.get(meeting.response_status, meeting.response_status)),
        ]
        if meeting.is_recurring:
            rows.append(("Repeats", "Yes"))
        if meeting.is_cancelled:
            rows.append(("Cancelled", "Yes"))
        for label, value in rows:
            facts_layout.addWidget(self._row(label, value))
        body_layout.addWidget(self._section("Details", self._card(facts)))

        people = list(meeting.required_attendees) + list(meeting.optional_attendees)
        attendee_text = "\n".join(_attendee_line(person) for person in people) or "No attendees"
        attendee_label = QLabel(attendee_text)
        attendee_label.setWordWrap(True)
        attendee_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_layout.addWidget(self._section("Attendees", self._card(attendee_label)))

        conflict_text = format_conflict_popup(meeting, report, meetings_by_id, tz)
        status = "Conflict detected" if report.has_conflict(meeting.uid) else "No conflict"
        conflict_box = QWidget()
        conflict_layout = QVBoxLayout(conflict_box)
        conflict_layout.setContentsMargins(0, 0, 0, 0)
        conflict_layout.setSpacing(6)
        conflict_layout.addWidget(self._row("Conflict", status))
        if conflict_text:
            box = QFrame()
            box.setObjectName("conflictBox")
            box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(10, 8, 10, 8)
            conflict = QLabel(conflict_text)
            conflict.setWordWrap(True)
            conflict.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            conflict.setStyleSheet(f"color: {colors()['conflict_text']}; background: transparent;")
            box_layout.addWidget(conflict)
            conflict_layout.addWidget(box)
        body_layout.addWidget(self._section("Schedule", conflict_box))

        description_html = body_to_html(meeting.body_html, meeting.body_text)
        if description_html and html_to_text(description_html):
            browser = QTextBrowser()
            browser.setObjectName("descriptionView")
            browser.setOpenExternalLinks(False)
            browser.setHtml(
                f"<body style='margin:0; font-family: {FONT_CSS}; font-size: 13px;'>{description_html}</body>"
            )
            browser.setMinimumHeight(90)
            browser.anchorClicked.connect(self._open_browser_url)
            body_layout.addWidget(self._section("Description", browser))
        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.link_button = make_button("Join Meeting", "primary")
        self.link_button.setFixedWidth(136)
        self.link_button.setVisible(bool(self._link))
        self.link_button.clicked.connect(self._open_meeting_link)
        close = make_button("Close", "secondary")
        close.setFixedWidth(96)
        close.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self.link_button)
        button_row.addStretch(1)
        button_row.addWidget(close)
        root.addLayout(button_row)

        note = QLabel("Read only. Meetings cannot be accepted, declined, changed, or deleted.")
        note.setObjectName("hintLabel")
        root.addWidget(note)

    def _card(self, body: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("statusCard")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(body)
        return frame

    def _section(self, title: str, body: QWidget) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)
        layout.addWidget(body)
        return section

    def _row(self, label: str, value: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        name = QLabel(label)
        name.setObjectName("factLabel")
        name.setMinimumWidth(110)
        text = QLabel(value)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(name)
        layout.addWidget(text, 1)
        return widget

    def _open_meeting_link(self) -> None:
        if self._link:
            _open_http_url(self._link)

    def _open_browser_url(self, url: QUrl) -> None:
        _open_http_url(url.toString())


def _join_link(meeting: Meeting) -> str:
    return meeting_url(meeting)


def _open_http_url(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return
    QDesktopServices.openUrl(QUrl(url))
