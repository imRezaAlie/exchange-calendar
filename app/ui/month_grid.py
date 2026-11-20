"""Month grid. Each date shows the meetings that fall on it."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import ConflictReport
from app.calendar.date_utils import intersects_day, month_grid_days
from app.models import Meeting
from app.ui.widgets import restyle


class _EventLink(QLabel):
    activated = Signal(object)

    def __init__(self, meeting: Meeting, conflict: bool) -> None:
        super().__init__((meeting.subject or "").strip() or "(No subject)")
        self.meeting = meeting
        self.setObjectName("monthEvent")
        self.setProperty("conflict", "true" if conflict else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(self.text())

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.meeting)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.meeting)
            return
        super().keyPressEvent(event)


class _DayCell(QFrame):
    day_selected = Signal(object)
    meeting_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._day: date | None = None
        self.setObjectName("monthCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(78)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        self.number = QLabel()
        self.number.setObjectName("monthNumber")
        self.number.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.number)
        self._events = QVBoxLayout()
        self._events.setContentsMargins(0, 0, 0, 0)
        self._events.setSpacing(1)
        layout.addLayout(self._events)
        layout.addStretch(1)

    def show_day(
        self,
        day: date,
        month: int,
        today: date,
        anchor: date,
        meetings: list[Meeting],
        report: ConflictReport,
        tz: ZoneInfo,
        highlight: bool,
    ) -> None:
        self._day = day
        self.number.setText(str(day.day))
        outside = day.month != month
        self.setProperty("outside", "true" if outside else "false")
        self.setProperty("today", "true" if day == today else "false")
        self.setProperty("selected", "true" if day == anchor else "false")
        restyle(self)
        restyle(self.number)
        while self._events.count():
            item = self._events.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        shown = 0
        for meeting in meetings:
            if not intersects_day(meeting.start, meeting.end, day, tz):
                continue
            if shown == 3:
                more = QLabel("More")
                more.setObjectName("monthMore")
                more.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self._events.addWidget(more)
                break
            link = _EventLink(meeting, highlight and report.has_conflict(meeting.uid))
            link.activated.connect(self.meeting_selected.emit)
            self._events.addWidget(link)
            shown += 1

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._day is not None:
            self.day_selected.emit(self._day)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._day is not None:
            self.day_selected.emit(self._day)
            return
        super().keyPressEvent(event)


class MonthGrid(QWidget):
    meeting_selected = Signal(object)
    day_selected = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 0, 12, 12)
        root.setSpacing(0)
        self._names = QGridLayout()
        self._names.setContentsMargins(0, 0, 0, 0)
        self._names.setSpacing(4)
        root.addLayout(self._names)
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 8, 0, 0)
        self._grid.setSpacing(4)
        root.addLayout(self._grid, 1)
        self._cells: list[_DayCell] = []
        self._name_labels: list[QLabel] = []

    def show_month(
        self,
        anchor: date,
        week_starts_on: str,
        meetings: list[Meeting],
        report: ConflictReport,
        tz: ZoneInfo,
        now: datetime,
        highlight: bool,
    ) -> None:
        days = month_grid_days(anchor, week_starts_on)
        today = now.astimezone(tz).date()
        self._ensure_cells(len(days), week_starts_on)
        ordered = sorted(
            meetings,
            key=lambda meeting: (not meeting.is_all_day, meeting.start, meeting.subject.lower()),
        )
        for index, day in enumerate(days):
            self._cells[index].show_day(day, anchor.month, today, anchor, ordered, report, tz, highlight)
            self._cells[index].show()
        for index in range(len(days), len(self._cells)):
            self._cells[index].hide()

    def _ensure_cells(self, count: int, week_starts_on: str) -> None:
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        if week_starts_on == "sunday":
            names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        if len(self._name_labels) != 7:
            while self._names.count():
                item = self._names.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self._name_labels = []
            for column, name in enumerate(names):
                label = QLabel(name.upper())
                label.setObjectName("sheetHead")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._names.addWidget(label, 0, column)
                self._name_labels.append(label)
        else:
            for label, name in zip(self._name_labels, names):
                label.setText(name.upper())
        while len(self._cells) < count:
            cell = _DayCell()
            cell.day_selected.connect(self.day_selected.emit)
            cell.meeting_selected.connect(self.meeting_selected.emit)
            row, column = divmod(len(self._cells), 7)
            self._grid.addWidget(cell, row, column)
            self._cells.append(cell)
