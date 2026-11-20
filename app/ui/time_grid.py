"""Time grid for the day and week. Events sit on the clock, not in a list."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import ConflictReport
from app.calendar.date_utils import as_utc, format_time_span, next_day, start_of_day
from app.calendar.links import meeting_url, place_name
from app.models import Meeting
from app.services.alarms import TodoRecord
from app.ui.colors import colors
from app.ui.widgets import restyle

HOUR_HEIGHT = 48
DAY_MINUTES = 24 * 60
GUTTER = 56
MIN_BLOCK = 22
COLUMN_MIN = 96


def minute_span(meeting: Meeting, day: date, tz: ZoneInfo) -> tuple[int, int] | None:
    """Wall-clock minutes of a timed meeting clipped to one local day.

    The top follows the configured timezone's clock. A daylight-saving fold,
    where the clock jumps backward and the wall-clock end is not after the
    start, falls back to the real elapsed minutes so the block still has height.
    """
    if meeting.is_all_day:
        return None
    day_start = as_utc(start_of_day(day, tz))
    day_end = as_utc(next_day(day, tz))
    start = as_utc(meeting.start)
    end = as_utc(meeting.end)
    if end <= day_start or start >= day_end:
        return None
    local_start = meeting.start.astimezone(tz)
    local_end = meeting.end.astimezone(tz)
    if local_start.date() < day:
        start_min = 0
    else:
        start_min = local_start.hour * 60 + local_start.minute
    if local_end.date() > day:
        end_min = DAY_MINUTES
    else:
        end_min = local_end.hour * 60 + local_end.minute
    if end_min <= start_min:
        clipped = int((min(end, day_end) - max(start, day_start)).total_seconds() // 60)
        end_min = min(DAY_MINUTES, start_min + max(clipped, 15))
    if end_min <= start_min:
        end_min = min(DAY_MINUTES, start_min + 15)
    return start_min, end_min


class EventBlock(QFrame):
    activated = Signal(object)

    def __init__(
        self,
        meeting: Meeting,
        report: ConflictReport,
        tz: ZoneInfo,
        now: datetime,
        highlight: bool,
    ) -> None:
        super().__init__()
        self.meeting = meeting
        self.start_min = 0
        self.end_min = 30
        self.column = 0
        self.columns = 1
        conflict = highlight and report.has_conflict(meeting.uid)
        ongoing = as_utc(meeting.start) <= as_utc(now) < as_utc(meeting.end)
        past = as_utc(meeting.end) <= as_utc(now) or meeting.is_cancelled
        subject = (meeting.subject or "").strip() or "(No subject)"
        span = format_time_span(meeting.start, meeting.end, tz, False).replace(" - ", "–")
        self.setObjectName("eventBlock")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(subject)
        self.setProperty("conflict", "true" if conflict else "false")
        self.setProperty("ongoing", "true" if ongoing and not conflict else "false")
        self.setProperty("past", "true" if past else "false")
        self.setProperty("selected", "false")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(0)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        self._title = QLabel(subject)
        self._title.setObjectName("eventTitle")
        self._title.setWordWrap(False)
        self._title.setMinimumSize(0, 0)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._when = QLabel(span)
        self._when.setObjectName("eventTime")
        self._when.setMinimumSize(0, 0)
        self._when.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._title)
        layout.addWidget(self._when)
        self._subject = subject
        self._span = span
        lines = [subject, span]
        organizer = (meeting.organizer_name or meeting.organizer_email or "").strip()
        location = place_name(meeting.location)
        if organizer:
            lines.append(organizer)
        if location:
            lines.append(location)
        if meeting.is_recurring:
            lines.append("Recurring")
        if conflict:
            lines.append("Overlaps another meeting")
        url = meeting_url(meeting)
        if url:
            lines.append(url)
        self.setToolTip("\n".join(lines))
        if past:
            ink = colors()["past"]
            self._title.setStyleSheet(f"color: {ink}; background: transparent; font-weight: 600;")
            self._when.setStyleSheet(f"color: {ink}; background: transparent;")

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        restyle(self)

    def apply_geometry(self, x: int, y: int, width: int, height: int) -> None:
        self.setGeometry(x, y, max(8, width), max(MIN_BLOCK, height))
        narrow = self.height() < 36
        self._when.setVisible(not narrow)
        fitted = self.fontMetrics().elidedText(self._subject, Qt.TextElideMode.ElideRight, max(8, self.width() - 12))
        self._title.setText(fitted if narrow else self._subject)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.meeting)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.meeting)
            return
        super().keyPressEvent(event)


class _DayHeading(QLabel):
    def __init__(self, day: date, today: date, alone: bool, signal: Signal) -> None:
        super().__init__(day.strftime("%a %d").upper())
        self._day = day
        self._signal = signal
        self.setObjectName("gridDay")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("today", "true" if day == today else "false")
        chosen = alone or day == today
        self.setProperty("selected", "true" if chosen else "false")
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._signal.emit(self._day)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._signal.emit(self._day)
            return
        super().keyPressEvent(event)


class _Chip(QFrame):
    activated = Signal(object)

    def __init__(self, text: str, payload, kind: str) -> None:
        super().__init__()
        self.payload = payload
        self.setObjectName("allDayChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("kind", kind)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(text)
        self.setFixedHeight(18)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        label = QLabel(text)
        label.setObjectName("eventTitle")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label)
        self.setToolTip(text)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.payload)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.payload)
            return
        super().keyPressEvent(event)


class _Hours(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(GUTTER)
        self.setFixedHeight(DAY_MINUTES // 60 * HOUR_HEIGHT)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(QColor(colors()["muted"]))
        for hour in range(24):
            y = hour * HOUR_HEIGHT
            painter.drawText(0, y + 4, GUTTER - 8, 16, Qt.AlignmentFlag.AlignRight, f"{hour:02d}:00")
        painter.end()


class _Canvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.days: list[date] = []
        self.today: date | None = None
        self.setMinimumHeight(DAY_MINUTES // 60 * HOUR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        palette = colors()
        width = self.width()
        height = self.height()
        count = max(1, len(self.days))
        column = width / count
        if self.today in self.days:
            index = self.days.index(self.today)
            painter.fillRect(int(index * column), 0, int(column) + 1, height, QColor(palette["hover"]))
        line = QPen(QColor(palette["row_line"]))
        line.setWidth(1)
        painter.setPen(line)
        for hour in range(25):
            y = hour * HOUR_HEIGHT
            painter.drawLine(0, y, width, y)
        painter.end()


class TimeGrid(QWidget):
    meeting_selected = Signal(object)
    task_selected = Signal(str)
    day_selected = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._days: list[date] = []
        self._blocks: list[EventBlock] = []
        self._now_minute: int | None = None
        self._selected = ""
        self._pending_scroll = False
        self._focus_minute = 8 * 60

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header_bar = QWidget()
        header_layout = QHBoxLayout(self._header_bar)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        gutter_head = QWidget()
        gutter_head.setFixedWidth(GUTTER)
        header_layout.addWidget(gutter_head)
        self._header_scroll = _locked_scroll()
        self._header_scroll.setFixedHeight(32)
        self._header_host = QWidget()
        self._header_row = QHBoxLayout(self._header_host)
        self._header_row.setContentsMargins(0, 0, 0, 0)
        self._header_row.setSpacing(0)
        self._header_scroll.setWidget(self._header_host)
        header_layout.addWidget(self._header_scroll, 1)
        root.addWidget(self._header_bar)

        self._allday_bar = QWidget()
        allday_layout = QHBoxLayout(self._allday_bar)
        allday_layout.setContentsMargins(0, 0, 0, 0)
        allday_layout.setSpacing(0)
        allday_label = QLabel("All day")
        allday_label.setObjectName("sheetHead")
        allday_label.setFixedWidth(GUTTER)
        allday_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        allday_layout.addWidget(allday_label)
        self._allday_scroll = _locked_scroll()
        self._allday_host = QWidget()
        self._allday_row = QHBoxLayout(self._allday_host)
        self._allday_row.setContentsMargins(0, 4, 0, 4)
        self._allday_row.setSpacing(0)
        self._allday_scroll.setWidget(self._allday_host)
        allday_layout.addWidget(self._allday_scroll, 1)
        self._allday_bar.hide()
        root.addWidget(self._allday_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._gutter_scroll = QScrollArea()
        self._gutter_scroll.setFixedWidth(GUTTER)
        self._gutter_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._gutter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gutter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gutter_scroll.setWidgetResizable(False)
        self._hours = _Hours()
        self._gutter_scroll.setWidget(self._hours)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._canvas = _Canvas()
        self._now_line = QFrame(self._canvas)
        self._now_line.setObjectName("nowLine")
        self._now_line.setFixedHeight(2)
        self._now_line.hide()
        self._scroll.setWidget(self._canvas)
        body_layout.addWidget(self._gutter_scroll)
        body_layout.addWidget(self._scroll, 1)
        root.addWidget(body, 1)
        self._scroll.verticalScrollBar().valueChanged.connect(self._gutter_scroll.verticalScrollBar().setValue)
        self._scroll.horizontalScrollBar().valueChanged.connect(self._sync_horizontal)

    def show_days(
        self,
        days: list[date],
        meetings: list[Meeting],
        todos: list[TodoRecord],
        report: ConflictReport,
        tz: ZoneInfo,
        now: datetime,
        highlight: bool,
        selected_uid: str,
        reset_scroll: bool,
    ) -> None:
        self._days = list(days)
        self._selected = selected_uid
        self._canvas.days = list(days)
        self._canvas.today = now.astimezone(tz).date()
        self._clear()
        self._build_headers(days, now.astimezone(tz).date())
        self._build_all_day(days, meetings, todos, tz)
        self._build_blocks(days, meetings, report, tz, now, highlight)
        today = now.astimezone(tz).date()
        if today in days:
            self._now_minute = now.astimezone(tz).hour * 60 + now.astimezone(tz).minute
            self._focus_minute = self._now_minute
            self._now_line.show()
        else:
            self._now_minute = None
            self._focus_minute = 8 * 60
            self._now_line.hide()
        self._pending_scroll = reset_scroll
        self._relayout()
        if reset_scroll and self.isVisible():
            self._scroll_to_focus()
            self._pending_scroll = False

    def reveal(self, uid: str) -> None:
        for block in self._blocks:
            if block.meeting.uid == uid:
                self._scroll.ensureWidgetVisible(block, 24, 80)
                block.setFocus()
                return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._relayout()
        if self._pending_scroll:
            self._scroll_to_focus()
            self._pending_scroll = False

    def _clear(self) -> None:
        for block in self._blocks:
            block.hide()
            block.setParent(None)
            block.deleteLater()
        self._blocks = []
        _empty(self._header_row)
        _empty(self._allday_row)

    def _build_headers(self, days: list[date], today: date) -> None:
        alone = len(days) == 1
        for day in days:
            heading = _DayHeading(day, today, alone, self.day_selected)
            if alone:
                heading.setProperty("selected", "true")
            self._header_row.addWidget(heading, 1)
            restyle(heading)

    def _build_all_day(self, days: list[date], meetings: list[Meeting], todos: list[TodoRecord], tz: ZoneInfo) -> None:
        any_items = False
        for day in days:
            column = QWidget()
            column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            layout = QVBoxLayout(column)
            layout.setContentsMargins(2, 0, 2, 0)
            layout.setSpacing(2)
            timed = 0
            for meeting in meetings:
                if not meeting.is_all_day:
                    continue
                if minute_span(meeting, day, tz) is not None or _all_day_on(meeting, day, tz):
                    chip = _Chip((meeting.subject or "All day").strip() or "All day", meeting, "event")
                    chip.activated.connect(self.meeting_selected.emit)
                    layout.addWidget(chip)
                    any_items = True
                    timed += 1
                    if timed == 3:
                        break
            for todo in todos:
                if todo.scheduled_date == day.isoformat():
                    chip = _Chip(todo.title or "Task", todo.uid, "task")
                    chip.activated.connect(self.task_selected.emit)
                    layout.addWidget(chip)
                    any_items = True
            layout.addStretch(1)
            self._allday_row.addWidget(column, 1)
        self._allday_bar.setVisible(any_items)

    def _build_blocks(
        self,
        days: list[date],
        meetings: list[Meeting],
        report: ConflictReport,
        tz: ZoneInfo,
        now: datetime,
        highlight: bool,
    ) -> None:
        for day_index, day in enumerate(days):
            placed: list[EventBlock] = []
            for meeting in meetings:
                if meeting.is_all_day:
                    continue
                span = minute_span(meeting, day, tz)
                if span is None:
                    continue
                block = EventBlock(meeting, report, tz, now, highlight)
                block.start_min, block.end_min = span
                block.day_index = day_index  # type: ignore[attr-defined]
                block.activated.connect(self.meeting_selected.emit)
                block.setParent(self._canvas)
                placed.append(block)
            _assign_columns(placed)
            for block in placed:
                block.set_selected(block.meeting.uid == self._selected)
                block.show()
            self._blocks.extend(placed)

    def _relayout(self) -> None:
        count = max(1, len(self._days))
        viewport = max(1, self._scroll.viewport().width())
        width = max(viewport, count * COLUMN_MIN)
        height = 24 * HOUR_HEIGHT
        self._canvas.setMinimumWidth(width)
        self._canvas.setFixedHeight(height)
        self._canvas.resize(width, height)
        self._hours.setFixedHeight(height)
        self._header_host.setFixedHeight(32)
        self._header_host.resize(width, 32)
        allday_height = max(28, self._allday_host.sizeHint().height())
        self._allday_host.setMinimumWidth(width)
        self._allday_host.resize(width, allday_height)
        self._allday_scroll.setFixedHeight(allday_height)
        for block in self._blocks:
            column_width = width / count
            inner = max(8, column_width - 6)
            slice_width = inner / max(1, block.columns)
            x = int(block.day_index * column_width + 3 + block.column * slice_width)
            y = int(block.start_min / 60 * HOUR_HEIGHT)
            block_height = max(MIN_BLOCK, int((block.end_min - block.start_min) / 60 * HOUR_HEIGHT) - 2)
            block.apply_geometry(x, y, max(8, int(slice_width) - 3), block_height)
        if self._now_minute is not None:
            y = int(self._now_minute / 60 * HOUR_HEIGHT)
            self._now_line.setGeometry(0, y, width, 2)
            self._now_line.raise_()
        self._sync_horizontal(self._scroll.horizontalScrollBar().value())
        self._gutter_scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().value())
        self._canvas.update()

    def _scroll_to_focus(self) -> None:
        y = max(0, int(self._focus_minute / 60 * HOUR_HEIGHT) - HOUR_HEIGHT)
        self._scroll.verticalScrollBar().setValue(y)

    def _sync_horizontal(self, value: int) -> None:
        self._header_scroll.horizontalScrollBar().setValue(int(value))
        self._allday_scroll.horizontalScrollBar().setValue(int(value))


def _locked_scroll() -> QScrollArea:
    area = QScrollArea()
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidgetResizable(False)
    return area


def _assign_columns(blocks: list[EventBlock]) -> None:
    ordered = sorted(blocks, key=lambda block: (block.start_min, block.end_min, block.meeting.subject.lower()))
    column_ends: list[int] = []
    for block in ordered:
        placed = False
        for index, column_end in enumerate(column_ends):
            if column_end <= block.start_min:
                block.column = index
                column_ends[index] = block.end_min
                placed = True
                break
        if not placed:
            block.column = len(column_ends)
            column_ends.append(block.end_min)
    for block in ordered:
        peers = [
            other
            for other in ordered
            if other.start_min < block.end_min and block.start_min < other.end_min
        ]
        block.columns = max(other.column for other in peers) + 1 if peers else 1


def _all_day_on(meeting: Meeting, day: date, tz: ZoneInfo) -> bool:
    start = meeting.start.astimezone(tz).date()
    end = meeting.end.astimezone(tz)
    # Exchange all-day items often end at midnight on the following day.
    end_day = end.date()
    if end.hour == 0 and end.minute == 0 and end_day > start:
        end_day = end_day.fromordinal(end_day.toordinal() - 1)
    return start <= day <= end_day


def _empty(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

