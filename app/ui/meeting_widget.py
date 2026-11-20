"""One agenda card: time, subject, organizer, place, and a status pill."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import ConflictReport, conflict_lines, format_conflict_popup
from app.calendar.date_utils import as_utc, format_time_span
from app.calendar.links import place_name
from app.models import Meeting
from app.services.alarms import TodoRecord
from app.ui.colors import colors
from app.ui.theme import FONT_CSS

TIME_WIDTH = 104
ORGANIZER_WIDTH = 128
LOCATION_WIDTH = 112
STATUS_WIDTH = 96
ROW_HEIGHT = 44


class _Cell(QLabel):
    def __init__(self, text: str, width: int | None, head: bool) -> None:
        super().__init__()
        self._full = text
        self._fitting = False
        self.setText(text)
        self.setObjectName("sheetHead" if head else "sheetCell")
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        if width is None:
            self.setMinimumWidth(48)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        else:
            self.setFixedWidth(width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fitting:
            return
        width = max(8, self.contentsRect().width() - 2)
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width)
        if elided == self.text():
            return
        self._fitting = True
        self.setText(elided)
        self._fitting = False


class _SheetRow(QFrame):
    def __init__(self, time: str, subject: str, organizer: str, location: str, status: str, head: bool = False) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8 if not head else 0, 0, 8 if not head else 0, 0)
        layout.setSpacing(0)
        self.time_label = _Cell(time, TIME_WIDTH, head)
        self.subject_label = _Cell(subject, None, head)
        self.organizer_label = _Cell(organizer, ORGANIZER_WIDTH, head)
        self.location_label = _Cell(location, LOCATION_WIDTH, head)
        self.status_label = _Cell(status, STATUS_WIDTH, head)
        if not head:
            self.subject_label.setObjectName("meetingSubject")
            self.organizer_label.setObjectName("meetingOrganizer")
            self.location_label.setObjectName("meetingLocation")
        for cell in (
            self.time_label,
            self.subject_label,
            self.organizer_label,
            self.location_label,
            self.status_label,
        ):
            layout.addWidget(cell)


class SheetHeader(_SheetRow):
    def __init__(self) -> None:
        super().__init__("Time", "Subject", "Organizer", "Location", "Status", head=True)
        self.setObjectName("sheetHeader")
        self.setFixedHeight(28)


class MeetingWidget(_SheetRow):
    clicked = Signal(object)

    def __init__(
        self,
        meeting: Meeting,
        report: ConflictReport,
        meetings_by_id: dict[str, Meeting],
        tz: ZoneInfo,
        now: datetime,
        highlight: bool,
        parent=None,
    ) -> None:
        conflict = highlight and report.has_conflict(meeting.uid)
        ongoing = not meeting.is_all_day and as_utc(meeting.start) <= as_utc(now) < as_utc(meeting.end)
        past = not meeting.is_all_day and as_utc(meeting.end) <= as_utc(now)
        span = format_time_span(meeting.start, meeting.end, tz, meeting.is_all_day).replace(" - ", "–")
        subject = (meeting.subject or "").strip() or "(No subject)"
        organizer_full = (meeting.organizer_name or meeting.organizer_email or "").strip()
        location_full = (meeting.location or "").strip()
        status = _status(meeting, report, meetings_by_id, conflict, ongoing)
        super().__init__(span, subject, _person(organizer_full), place_name(location_full), status)
        self.meeting = meeting
        self.setObjectName("meetingRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("conflict", "true" if conflict else "false")
        self.setProperty("ongoing", "true" if ongoing and not conflict else "false")
        self.setProperty("past", "true" if past or meeting.is_cancelled else "false")

        palette = colors()
        if past or meeting.is_cancelled:
            color = palette["past"]
        else:
            color = palette["text"]
        strike = "text-decoration: line-through;" if meeting.is_cancelled else ""
        style = f"color: {color}; background: transparent; font-size: 13px; {strike}"
        self.time_label.setStyleSheet(
            style + f"font-family: {FONT_CSS}; font-size: 12px;"
        )
        self.subject_label.setStyleSheet(style + "font-weight: 600;")
        self.organizer_label.setStyleSheet(style)
        self.location_label.setStyleSheet(style)
        if status:
            if conflict:
                fill, ink, border = "transparent", palette["conflict_text"], palette["conflict_line"]
            elif ongoing:
                fill, ink, border = palette["ongoing_bg"], palette["text"], palette["ongoing_line"]
            else:
                fill, ink, border = palette["sheet_band"], palette["summary"], palette["card_line"]
            self.status_label.setObjectName("statusPill")
            self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.status_label.setFixedHeight(20)
            self.layout().setAlignment(self.status_label, Qt.AlignmentFlag.AlignVCenter)
            self.status_label.setStyleSheet(
                f"color: {ink}; background: {fill}; border: 1px solid {border}; border-radius: 4px; padding: 0 6px; font-size: 11px; font-weight: 700;"
            )
        else:
            self.status_label.setStyleSheet("color: transparent; background: transparent;")
        if organizer_full:
            self.organizer_label.setToolTip(organizer_full)
        if location_full:
            self.location_label.setToolTip(location_full)
        if conflict:
            popup = format_conflict_popup(meeting, report, meetings_by_id, tz)
            if popup:
                self.setToolTip(popup)
        else:
            details = [line for line in (subject, organizer_full, location_full) if line]
            if details:
                self.setToolTip("\n".join(details))

    def mousePressEvent(self, event) -> None:
        left_click = event.button() == Qt.MouseButton.LeftButton
        meeting = self.meeting
        try:
            super().mousePressEvent(event)
        except RuntimeError:
            return
        if left_click:
            self.clicked.emit(meeting)

    def keyPressEvent(self, event) -> None:
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            super().keyPressEvent(event)
            return
        meeting = self.meeting
        try:
            super().keyPressEvent(event)
        except RuntimeError:
            return
        self.clicked.emit(meeting)


class TaskWidget(QFrame):
    """One task, shown apart from the meeting sheet."""

    clicked = Signal(str)

    def __init__(self, todo: TodoRecord, parent=None) -> None:
        super().__init__(parent)
        self.todo = todo
        title = todo.title.strip() or "Task"
        clock = todo.reminder_time.strip() or "—"
        done = todo.completed
        self.setObjectName("agendaTask")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("done", "true" if done else "false")
        self.setProperty("priority", "high" if todo.priority == "high" and not done else "normal")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)
        self.time_label = QLabel(clock)
        self.time_label.setObjectName("taskTime")
        self.time_label.setFixedWidth(72)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("taskTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.status_label = QLabel(_task_status(todo))
        self.status_label.setObjectName("statusPill")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFixedSize(STATUS_WIDTH, 20)
        layout.addWidget(self.time_label)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.status_label)

        palette = colors()
        color = palette["past"] if done else palette["text"]
        strike = "text-decoration: line-through;" if done else ""
        style = f"color: {color}; background: transparent; font-size: 13px; {strike}"
        self.time_label.setStyleSheet(
            style + f"font-family: {FONT_CSS}; font-size: 12px;"
        )
        self.title_label.setStyleSheet(style + "font-weight: 600;")
        if done:
            fill, ink, border = palette["sheet_band"], palette["past"], palette["card_line"]
        elif todo.priority == "high":
            fill, ink, border = palette["accent"], palette["on_accent"], palette["accent"]
        else:
            fill, ink, border = "transparent", palette["summary"], palette["card_line"]
        self.status_label.setStyleSheet(
            f"color: {ink}; background: {fill}; border: 1px solid {border}; border-radius: 4px; padding: 0 6px; font-size: 11px; font-weight: 700;"
        )
        details = [title]
        if todo.reminder_time.strip():
            details.append(todo.reminder_time.strip())
        if todo.notes.strip():
            details.append(todo.notes.strip())
        self.setToolTip("\n".join(details))

    def mousePressEvent(self, event) -> None:
        left_click = event.button() == Qt.MouseButton.LeftButton
        uid = self.todo.uid
        try:
            super().mousePressEvent(event)
        except RuntimeError:
            return
        if left_click and uid:
            self.clicked.emit(uid)

    def keyPressEvent(self, event) -> None:
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            super().keyPressEvent(event)
            return
        uid = self.todo.uid
        try:
            super().keyPressEvent(event)
        except RuntimeError:
            return
        if uid:
            self.clicked.emit(uid)


def _task_status(todo: TodoRecord) -> str:
    if todo.completed:
        return "Done"
    if todo.priority == "high":
        return "High"
    if todo.priority == "low":
        return "Low"
    return "Open"


def _person(name: str) -> str:
    text = name.strip()
    bracket = text.find(" [")
    if bracket > 1:
        return text[:bracket].strip()
    return text


def _status(
    meeting: Meeting,
    report: ConflictReport,
    meetings_by_id: dict[str, Meeting],
    conflict: bool,
    ongoing: bool,
) -> str:
    if conflict:
        _title, detail = conflict_lines(meeting, report, meetings_by_id)
        if detail.startswith("Overlap: "):
            return detail.removeprefix("Overlap: ").replace("minutes", "min").replace("minute", "min")
        return "Conflict"
    if meeting.is_cancelled:
        return "Cancelled"
    if ongoing:
        return "Now"
        if meeting.is_recurring:
            return "Recurring"
    if meeting.is_all_day:
        return "All day"
    return ""
