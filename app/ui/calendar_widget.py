"""Calendar workspace: navigation, the current meeting, and day, week, month, or agenda."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from zoneinfo import ZoneInfo

from app.calendar.agenda import agenda_at
from app.calendar.conflict_detector import ConflictReport
from app.calendar.date_utils import (
    as_utc,
    format_long_date,
    format_week_span,
    intersects_day,
    shift_anchor,
    start_of_day,
    visible_days,
    next_day,
)
from app.models import Meeting
from app.services.alarms import TodoRecord
from app.ui.colors import colors
from app.ui.icons import chevron_icon
from app.ui.meeting_widget import MeetingWidget, SheetHeader, TaskWidget
from app.ui.month_grid import MonthGrid
from app.ui.now_next import NowNextBar
from app.ui.time_grid import TimeGrid
from app.ui.widgets import make_button

_VIEWS = ("daily", "weekly", "monthly", "agenda")


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            _clear_layout(child)


class CalendarWidget(QWidget):
    meeting_selected = Signal(object)
    task_selected = Signal(str)
    anchor_changed = Signal()
    conflicts_requested = Signal()

    def __init__(self, tz: ZoneInfo, week_starts_on: str, view: str, parent=None) -> None:
        super().__init__(parent)
        self._tz = tz
        self._week_starts_on = week_starts_on
        self._view = view if view in _VIEWS else "weekly"
        self._anchor = datetime.now(tz).date()
        self._highlight = True
        self._meetings: list[Meeting] = []
        self._todos: list[TodoRecord] = []
        self._report = ConflictReport()
        self._by_id: dict[str, Meeting] = {}
        self._window_start: datetime | None = None
        self._window_end: datetime | None = None
        self._empty_reason = "Loading calendar…"
        self._rendered: list[Meeting] = []
        self._selected_uid = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.cache_banner = QLabel()
        self.cache_banner.setObjectName("cacheBanner")
        self.cache_banner.setWordWrap(True)
        self.cache_banner.hide()
        root.addWidget(self.cache_banner)

        root.addWidget(self._build_toolbar())

        self.now_next = NowNextBar()
        self.now_next.open_requested.connect(self.meeting_selected.emit, Qt.ConnectionType.QueuedConnection)
        root.addWidget(self.now_next)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("emptyDay")
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        root.addWidget(self.empty_label)

        self.time_grid = TimeGrid()
        self.time_grid.meeting_selected.connect(self._choose_meeting)
        self.time_grid.task_selected.connect(self.task_selected.emit)
        self.time_grid.day_selected.connect(self._on_day_chosen)
        self.month_grid = MonthGrid()
        self.month_grid.meeting_selected.connect(self._choose_meeting)
        self.month_grid.day_selected.connect(self._on_month_day)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(16, 0, 16, 16)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch(1)
        self.scroll.viewport().setObjectName("agendaViewport")
        self.list_host.setObjectName("agendaList")
        self.scroll.setWidget(self.list_host)

        self._stack = QStackedWidget()
        self._stack.addWidget(self.time_grid)
        self._stack.addWidget(self.month_grid)
        self._stack.addWidget(self.scroll)
        root.addWidget(self._stack, 1)
        self._sync_date_edit()
        self.refresh_icons()
        self.rebuild(reset_scroll=True)

    def _build_toolbar(self) -> QWidget:
        nav = QWidget()
        nav.setObjectName("navBar")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(12, 8, 12, 8)
        nav_layout.setSpacing(8)
        self.today_button = make_button("Today", "secondary")
        self.previous_button = make_button("", "icon")
        self.next_button = make_button("", "icon")
        self.previous_button.setToolTip("Previous (Ctrl+Left)")
        self.today_button.setToolTip("Today (Ctrl+T)")
        self.next_button.setToolTip("Next (Ctrl+Right)")
        self.previous_button.clicked.connect(self.go_previous)
        self.today_button.clicked.connect(self.go_today)
        self.next_button.clicked.connect(self.go_next)
        nav_layout.addWidget(self.today_button)
        nav_layout.addWidget(self.previous_button)
        nav_layout.addWidget(self.next_button)
        self.period_label = QLabel()
        self.period_label.setObjectName("periodLabel")
        nav_layout.addWidget(self.period_label, 1)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("ddd MMM d, yyyy")
        self.date_edit.setFixedWidth(156)
        self.date_edit.setToolTip("Jump to a date")
        self.date_edit.dateChanged.connect(self._on_date_changed)
        nav_layout.addWidget(self.date_edit)
        self.conflict_button = make_button("", "danger")
        self.conflict_button.setToolTip("Review overlapping meetings")
        self.conflict_button.clicked.connect(self.conflicts_requested.emit)
        self.conflict_button.hide()
        nav_layout.addWidget(self.conflict_button)

        self.daily_button = make_button("Day", "toggle")
        self.weekly_button = make_button("Week", "toggle")
        self.monthly_button = make_button("Month", "toggle")
        self.agenda_button = make_button("Agenda", "toggle")
        buttons = (
            (self.daily_button, "daily", "Day view (Ctrl+1)"),
            (self.weekly_button, "weekly", "Week view (Ctrl+2)"),
            (self.monthly_button, "monthly", "Month view (Ctrl+3)"),
            (self.agenda_button, "agenda", "Agenda view (Ctrl+4)"),
        )
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for index, (button, _name, tip) in enumerate(buttons):
            button.setCheckable(True)
            button.setToolTip(tip)
            self._view_group.addButton(button, index)
            nav_layout.addWidget(button)
        self._sync_view_buttons()
        self._view_group.idClicked.connect(self._on_view_id)
        return nav

    def refresh_icons(self) -> None:
        ink = colors()["text"]
        self.previous_button.setIcon(chevron_icon("left", 14, ink))
        self.next_button.setIcon(chevron_icon("right", 14, ink))

    @property
    def anchor(self) -> date:
        return self._anchor

    @property
    def view(self) -> str:
        return self._view

    def subjects(self) -> list[str]:
        return [meeting.subject for meeting in self._rendered]

    def day_count(self) -> int:
        return len(visible_days(self._anchor, self._view, self._week_starts_on))

    def visible_range(self) -> tuple[datetime, datetime]:
        days = visible_days(self._anchor, self._view, self._week_starts_on)
        return start_of_day(days[0], self._tz), next_day(days[-1], self._tz)

    def outside_synced_window(self) -> bool:
        if self._window_start is None or self._window_end is None:
            return False
        start, end = self.visible_range()
        return end <= self._window_start or start >= self._window_end

    def set_banner(self, text: str) -> None:
        self.cache_banner.setText(text)
        self.cache_banner.setVisible(bool(text))

    def set_empty_reason(self, text: str) -> None:
        self._empty_reason = text

    def set_meetings(
        self,
        meetings: list[Meeting],
        report: ConflictReport,
        window_start: datetime | None,
        window_end: datetime | None,
        reset_scroll: bool = False,
    ) -> None:
        self._meetings = list(meetings)
        self._report = report
        self._by_id = {meeting.uid: meeting for meeting in meetings}
        self._window_start = window_start
        self._window_end = window_end
        self.rebuild(reset_scroll=reset_scroll)

    def set_todos(self, todos: list[TodoRecord], *, rebuild: bool = True) -> None:
        self._todos = list(todos)
        if rebuild:
            self.rebuild(reset_scroll=False)

    def apply_preferences(self, week_starts_on: str, view: str | None, tz: ZoneInfo, highlight: bool) -> None:
        self._week_starts_on = week_starts_on
        self._tz = tz
        self._highlight = highlight
        if view and view in _VIEWS and view != self._view:
            self.set_view(view)
        else:
            self.rebuild(reset_scroll=False)

    def set_view(self, view: str) -> None:
        if view not in _VIEWS:
            return
        self._view = view
        self._sync_view_buttons()
        self.rebuild(reset_scroll=True)
        self.anchor_changed.emit()

    def focus_meeting(self, meeting: Meeting) -> None:
        self._selected_uid = meeting.uid
        day = meeting.start.astimezone(self._tz).date()
        visible = visible_days(self._anchor, self._view, self._week_starts_on)
        moved = day not in visible
        if moved:
            self._anchor = day
        self.rebuild(reset_scroll=False)
        if self._view in {"daily", "weekly"}:
            self.time_grid.reveal(meeting.uid)
        if moved:
            self.anchor_changed.emit()

    def go_previous(self) -> None:
        self._anchor = shift_anchor(self._anchor, self._view, -1)
        self.rebuild(reset_scroll=True)
        self.anchor_changed.emit()

    def go_next(self) -> None:
        self._anchor = shift_anchor(self._anchor, self._view, 1)
        self.rebuild(reset_scroll=True)
        self.anchor_changed.emit()

    def go_today(self) -> None:
        self._anchor = datetime.now(self._tz).date()
        self.rebuild(reset_scroll=True)
        self.anchor_changed.emit()

    def _on_view_id(self, index: int) -> None:
        view = _VIEWS[index]
        if view == self._view:
            return
        self._view = view
        self.rebuild(reset_scroll=True)
        self.anchor_changed.emit()

    def _sync_view_buttons(self) -> None:
        mapping = {
            "daily": self.daily_button,
            "weekly": self.weekly_button,
            "monthly": self.monthly_button,
            "agenda": self.agenda_button,
        }
        for name, button in mapping.items():
            button.blockSignals(True)
            button.setChecked(name == self._view)
            button.blockSignals(False)

    def _on_date_changed(self, qdate: QDate) -> None:
        chosen = date(qdate.year(), qdate.month(), qdate.day())
        if chosen == self._anchor:
            return
        self._anchor = chosen
        self.rebuild(reset_scroll=True)
        self.anchor_changed.emit()

    def _sync_date_edit(self) -> None:
        qdate = QDate(self._anchor.year, self._anchor.month, self._anchor.day)
        self.date_edit.blockSignals(True)
        self.date_edit.setDate(qdate)
        self.date_edit.blockSignals(False)

    def _on_day_chosen(self, day: date) -> None:
        self._anchor = day
        if self._view != "daily":
            self.set_view("daily")
            return
        self.rebuild(reset_scroll=True)
        self.anchor_changed.emit()

    def _on_month_day(self, day: date) -> None:
        self._anchor = day
        self.set_view("daily")

    def _choose_meeting(self, meeting: Meeting) -> None:
        self._selected_uid = meeting.uid
        self.meeting_selected.emit(meeting)

    def rebuild(self, reset_scroll: bool) -> None:
        self._sync_date_edit()
        now = datetime.now(self._tz)
        today = now.date()
        days = visible_days(self._anchor, self._view, self._week_starts_on)
        self._update_period(today)
        rendered, grouped, conflict_ids = self._collect(days)
        self._rendered = rendered
        self._update_conflict_chip(len(conflict_ids))
        current, upcoming = agenda_at(self._meetings, now)
        self.now_next.show_agenda(current, upcoming, now, self._tz)
        self.now_next.show_openings(self._meetings, now, self._week_starts_on)
        self.empty_label.setText(self._empty_reason)
        self.empty_label.setVisible(bool(self._empty_reason) and not self._meetings and not self._todos)

        if self._view in {"daily", "weekly"}:
            self._stack.setCurrentWidget(self.time_grid)
            self.time_grid.show_days(
                days,
                self._meetings,
                self._todos_for(days),
                self._report,
                self._tz,
                now,
                self._highlight,
                self._selected_uid,
                reset_scroll,
            )
            _clear_layout(self.list_layout)
            self.list_layout.addStretch(1)
            return
        if self._view == "monthly":
            self._stack.setCurrentWidget(self.month_grid)
            self.month_grid.show_month(
                self._anchor,
                self._week_starts_on,
                self._meetings,
                self._report,
                self._tz,
                now,
                self._highlight,
            )
            _clear_layout(self.list_layout)
            self.list_layout.addStretch(1)
            return
        self._stack.setCurrentWidget(self.scroll)
        self._fill_agenda(grouped, today, now, reset_scroll)

    def _todos_for(self, days: list[date]) -> list[TodoRecord]:
        keys = {day.isoformat() for day in days}
        return [todo for todo in self._todos if todo.scheduled_date in keys]

    def _update_period(self, today: date) -> None:
        if self._view == "monthly":
            self.period_label.setText(self._anchor.strftime("%B %Y"))
            return
        if self._view in {"weekly", "agenda"}:
            days = visible_days(self._anchor, "weekly", self._week_starts_on)
            self.period_label.setText(format_week_span(days[0], days[-1]))
            return
        if self._anchor == today:
            self.period_label.setText("Today")
        else:
            self.period_label.setText(format_long_date(self._anchor))

    def _update_conflict_chip(self, count: int) -> None:
        if count <= 0:
            self.conflict_button.hide()
            return
        noun = "conflict" if count == 1 else "conflicts"
        self.conflict_button.setText(f"{count} {noun}")
        self.conflict_button.show()

    def _collect(self, days: list[date]):
        rendered: list[Meeting] = []
        conflict_ids: set[str] = set()
        grouped: list[tuple[date, list[Meeting]]] = []
        seen: set[str] = set()
        for day in days:
            day_meetings = [
                meeting
                for meeting in self._meetings
                if intersects_day(meeting.start, meeting.end, day, self._tz)
            ]
            day_meetings.sort(
                key=lambda meeting: (
                    not meeting.is_all_day,
                    as_utc(meeting.start),
                    as_utc(meeting.end),
                    meeting.subject.lower(),
                )
            )
            grouped.append((day, day_meetings))
            for meeting in day_meetings:
                if meeting.uid not in seen:
                    seen.add(meeting.uid)
                    rendered.append(meeting)
                if self._report.has_conflict(meeting.uid):
                    conflict_ids.add(meeting.uid)
        return rendered, grouped, conflict_ids

    def _fill_agenda(self, grouped, today: date, now: datetime, reset_scroll: bool) -> None:
        scrollbar = self.scroll.verticalScrollBar()
        position = 0 if reset_scroll else scrollbar.value()
        _clear_layout(self.list_layout)
        days = [day for day, _meetings in grouped]
        visible_tasks = any(self._todos_on(day) for day in days)
        if not self._meetings and self._empty_reason and not visible_tasks:
            message = QLabel(self._empty_reason)
            message.setWordWrap(True)
            message.setObjectName("emptyDay")
            self.list_layout.addWidget(message)
            self.list_layout.addStretch(1)
            scrollbar.setValue(position)
            return
        for day, day_meetings in grouped:
            header = QLabel(self._day_title(day, today))
            header.setTextFormat(Qt.TextFormat.PlainText)
            header.setObjectName("dayHeaderToday" if day == today else "dayHeader")
            self.list_layout.addWidget(header)
            day_tasks = sorted(self._todos_on(day), key=lambda todo: _todo_sort(todo, day, self._tz))
            if not day_meetings and not day_tasks:
                empty = QLabel("Nothing scheduled")
                empty.setObjectName("emptyDay")
                self.list_layout.addWidget(empty)
                continue
            if day_meetings:
                self.list_layout.addWidget(SheetHeader())
                for meeting in day_meetings:
                    row = MeetingWidget(meeting, self._report, self._by_id, self._tz, now, self._highlight)
                    row.setProperty("selected", "true" if meeting.uid == self._selected_uid else "false")
                    row.clicked.connect(self._choose_meeting, Qt.ConnectionType.QueuedConnection)
                    self.list_layout.addWidget(row)
            if day_tasks:
                group = QLabel("Tasks")
                group.setObjectName("taskGroup")
                self.list_layout.addWidget(group)
                for todo in day_tasks:
                    row = TaskWidget(todo)
                    row.clicked.connect(self.task_selected.emit, Qt.ConnectionType.QueuedConnection)
                    self.list_layout.addWidget(row)
        self.list_layout.addStretch(1)
        scrollbar.setValue(position)

    def _day_title(self, day: date, today: date) -> str:
        if day == today:
            title = f"Today — {day.strftime('%A, %B')} {day.day}"
        elif day == today + timedelta(days=1):
            title = f"Tomorrow — {day.strftime('%A, %B')} {day.day}"
        else:
            title = f"{day.strftime('%A, %B')} {day.day}"
        count = len(self._todos_on(day))
        if count == 1:
            title = f"{title} · 1 task"
        elif count:
            title = f"{title} · {count} tasks"
        return title

    def _todos_on(self, day: date) -> list[TodoRecord]:
        key = day.isoformat()
        return [todo for todo in self._todos if todo.scheduled_date == key]

def _parse_clock(value: str) -> tuple[int, int] | None:
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _todo_sort(todo: TodoRecord, day: date, tz: ZoneInfo) -> tuple:
    clock = _parse_clock(todo.reminder_time)
    if clock is None:
        return (0, "", "", todo.title.lower(), todo.uid)
    hour, minute = clock
    stamp = as_utc(datetime.combine(day, time(hour, minute), tzinfo=tz)).isoformat()
    return (1, stamp, stamp, todo.title.lower(), todo.uid)
