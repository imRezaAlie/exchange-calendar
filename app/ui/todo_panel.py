"""Today's tasks. One Add button; everything else lives in the row menu."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.alarms import TodoRecord
from app.storage.reminders import ReminderStore
from app.ui.widgets import SectionHeader, make_button, restyle

_PRIORITY = {"high": "High", "normal": "Normal", "low": "Low"}


class _TaskRow(QFrame):
    toggled = Signal(str, bool)
    chosen = Signal(str)
    menu_requested = Signal(str, object)

    def __init__(self, todo: TodoRecord, today: date) -> None:
        super().__init__()
        self.uid = todo.uid
        self.setObjectName("taskRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        self.box = QCheckBox()
        self.box.setChecked(todo.completed)
        self.box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.box.toggled.connect(lambda checked: self.toggled.emit(self.uid, checked))
        layout.addWidget(self.box)

        title = QLabel(todo.title or "Task")
        title.setObjectName("taskTitle")
        state = _state(todo, today)
        title.setProperty("state", state)
        if todo.completed:
            title.setStyleSheet("text-decoration: line-through;")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(title, 1)

        if todo.priority == "high" and not todo.completed:
            badge = QLabel("High")
            badge.setObjectName("priorityBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedHeight(18)
            badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(badge)

        meta = _meta(todo, today)
        if meta:
            when = QLabel(meta)
            when.setObjectName("taskMeta")
            when.setProperty("state", "overdue" if state == "overdue" else "pending")
            when.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(when)

        if todo.carried and not todo.completed:
            arrow = QLabel("→")
            arrow.setObjectName("carryMark")
            arrow.setToolTip("Carried forward")
            arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(arrow)

        self.setProperty("selected", "false")

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        restyle(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.uid)
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.uid, event.globalPosition().toPoint())
        super().mousePressEvent(event)


class TodoPanel(QWidget):
    changed = Signal()

    def __init__(self, store: ReminderStore, today: date, default_time: str, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._today = today
        self._default_time = default_time or "09:00"
        self._selected = ""
        self._editing = ""
        self._rows: list[_TaskRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = SectionHeader("Tasks")
        self.add_button = make_button("Add Task", "secondary")
        self.add_button.setFixedWidth(112)
        self.add_button.clicked.connect(self._start_add)
        self._header.add_trailing(self.add_button)
        root.addWidget(self._header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(0, 0, 0, 8)
        self._list.setSpacing(0)
        self._list.addStretch(1)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)

        self._detail = QLabel("Select a task to see its details.")
        self._detail.setObjectName("hintLabel")
        self._detail.setWordWrap(True)
        self._detail.setContentsMargins(16, 8, 16, 8)
        root.addWidget(self._detail)

        self._composer = QWidget()
        self._composer.setObjectName("composer")
        self._composer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QVBoxLayout(self._composer)
        form.setContentsMargins(16, 12, 16, 12)
        form.setSpacing(8)
        self._title = QLineEdit()
        self._title.setPlaceholderText("Task title")
        form.addWidget(self._title)
        self._day = QDateEdit()
        self._day.setCalendarPopup(True)
        self._day.setDisplayFormat("dd MMM yyyy")
        self._clock = QTimeEdit()
        self._clock.setDisplayFormat("HH:mm")
        self._remind = QCheckBox("Remind")
        self._remind.setChecked(True)
        self._remind.toggled.connect(self._clock.setEnabled)
        self._priority = QComboBox()
        self._priority.addItem("High", "high")
        self._priority.addItem("Normal", "normal")
        self._priority.addItem("Low", "low")
        self._priority.setCurrentIndex(1)
        when = QHBoxLayout()
        when.setSpacing(8)
        when.addWidget(self._day, 1)
        when.addWidget(self._clock)
        form.addLayout(when)
        priority_row = QHBoxLayout()
        priority_row.setSpacing(8)
        priority_row.addWidget(self._remind)
        priority_row.addWidget(self._priority, 1)
        form.addLayout(priority_row)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._save = make_button("Save", "primary")
        self._cancel = make_button("Cancel", "secondary")
        self._save.setFixedWidth(96)
        self._cancel.setFixedWidth(96)
        self._save.clicked.connect(self._save_task)
        self._cancel.clicked.connect(self._close_composer)
        actions.addWidget(self._save)
        actions.addWidget(self._cancel)
        actions.addStretch(1)
        form.addLayout(actions)
        self._composer.hide()
        root.addWidget(self._composer)
        self._apply_default_clock()
        self.reload()

    def set_today(self, today: date) -> None:
        self._today = today

    def set_default_time(self, value: str) -> None:
        self._default_time = value or "09:00"

    def reload(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        todos = _ordered(self.store.todos, self._today)
        if not todos:
            empty = QLabel("No tasks yet. Add one when you need a reminder that is not a meeting.")
            empty.setObjectName("emptyDay")
            empty.setWordWrap(True)
            self._list.addWidget(empty)
        previous = ""
        for todo in todos:
            bucket = _bucket(todo, self._today)
            if bucket != previous:
                heading = QLabel(bucket)
                heading.setObjectName("taskGroup")
                self._list.addWidget(heading)
                previous = bucket
            row = _TaskRow(todo, self._today)
            row.toggled.connect(self._on_toggled)
            row.chosen.connect(self.select)
            row.menu_requested.connect(self._open_menu)
            row.set_selected(todo.uid == self._selected)
            self._list.addWidget(row)
            self._rows.append(row)
        self._list.addStretch(1)
        self._show_detail()

    def select(self, uid: str) -> None:
        self._selected = uid
        for row in self._rows:
            row.set_selected(row.uid == uid)
        self._show_detail()

    def _show_detail(self) -> None:
        todo = self._find(self._selected)
        if todo is None:
            self._detail.setText("Select a task to see its details.")
            return
        parts = [todo.title or "Task"]
        parts.append(f"Due {todo.scheduled_date or '—'}")
        if todo.reminder_time:
            parts.append(f"Reminder {todo.reminder_time}")
        else:
            parts.append("No reminder")
        parts.append(_PRIORITY.get(todo.priority, "Normal"))
        if todo.completed:
            parts.append("Completed")
        elif _state(todo, self._today) == "overdue":
            parts.append("Overdue")
        if todo.carried and not todo.completed:
            parts.append("Carried forward")
        self._detail.setText("  ·  ".join(parts))

    def _start_add(self) -> None:
        self._editing = ""
        self._title.clear()
        self._day.setDate(QDate(self._today.year, self._today.month, self._today.day))
        self._remind.setChecked(True)
        self._apply_default_clock()
        self._priority.setCurrentIndex(1)
        self._save.setText("Save")
        self._composer.show()
        self._title.setFocus()

    def _start_edit(self, uid: str) -> None:
        todo = self._find(uid)
        if todo is None:
            return
        self.select(uid)
        self._editing = uid
        self._title.setText(todo.title)
        try:
            year, month, day = (int(part) for part in todo.scheduled_date.split("-"))
            self._day.setDate(QDate(year, month, day))
        except ValueError:
            self._day.setDate(QDate(self._today.year, self._today.month, self._today.day))
        if todo.reminder_time:
            hour, minute = _clock(todo.reminder_time)
            self._clock.setTime(QTime(hour, minute))
            self._remind.setChecked(True)
        else:
            self._remind.setChecked(False)
        index = self._priority.findData(todo.priority)
        self._priority.setCurrentIndex(index if index >= 0 else 1)
        self._composer.show()
        self._title.setFocus()

    def _close_composer(self) -> None:
        self._editing = ""
        self._composer.hide()

    def _save_task(self) -> None:
        title = self._title.text().strip()
        if not title:
            self._title.setFocus()
            return
        chosen = self._day.date()
        scheduled = date(chosen.year(), chosen.month(), chosen.day()).isoformat()
        reminder = ""
        if self._remind.isChecked():
            clock = self._clock.time()
            reminder = f"{clock.hour():02d}:{clock.minute():02d}"
        priority = str(self._priority.currentData())
        if self._editing:
            self.store.update_todo(self._editing, title, scheduled, reminder, priority)
            self._selected = self._editing
        else:
            created = self.store.add_todo(title, scheduled, reminder, priority)
            self._selected = created.uid
        self._close_composer()
        self.reload()
        self.changed.emit()

    def _on_toggled(self, uid: str, checked: bool) -> None:
        todo = self._find(uid)
        if todo is None or todo.completed == checked:
            return
        if checked:
            self.store.complete(uid)
        else:
            todo.completed = False
            self.store.save()
        self._selected = uid
        self.reload()
        self.changed.emit()

    def _open_menu(self, uid: str, global_pos) -> None:
        todo = self._find(uid)
        if todo is None:
            return
        self.select(uid)
        menu = QMenu(self)
        menu.addAction("Edit", lambda: self._start_edit(uid))
        menu.addAction("Reschedule", lambda: self._reschedule(uid))
        priority = menu.addMenu("Priority")
        for label, value in (("High", "high"), ("Normal", "normal"), ("Low", "low")):
            priority.addAction(label, lambda chosen=value: self._set_priority(uid, chosen))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self._delete(uid))
        menu.exec(global_pos)

    def _reschedule(self, uid: str) -> None:
        self._start_edit(uid)
        self._day.setFocus()

    def _set_priority(self, uid: str, priority: str) -> None:
        todo = self._find(uid)
        if todo is None:
            return
        self.store.update_todo(uid, todo.title, todo.scheduled_date, todo.reminder_time, priority)
        self.reload()
        self.changed.emit()

    def _delete(self, uid: str) -> None:
        todo = self._find(uid)
        if todo is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete task")
        box.setText(f"Delete “{todo.title}”?")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        yes = box.button(QMessageBox.StandardButton.Yes)
        if yes is not None:
            yes.setText("Delete")
            yes.setObjectName("btnDanger")
            restyle(yes)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(uid)
        if self._selected == uid:
            self._selected = ""
        if self._editing == uid:
            self._close_composer()
        self.reload()
        self.changed.emit()

    def _find(self, uid: str) -> TodoRecord | None:
        return next((item for item in self.store.todos if item.uid == uid), None)

    def _apply_default_clock(self) -> None:
        hour, minute = _clock(self._default_time)
        self._clock.setTime(QTime(hour, minute))
        self._clock.setEnabled(self._remind.isChecked())


def _state(todo: TodoRecord, today: date) -> str:
    if todo.completed:
        return "done"
    try:
        scheduled = date.fromisoformat(todo.scheduled_date)
    except ValueError:
        return "pending"
    if scheduled < today:
        return "overdue"
    return "pending"


def _meta(todo: TodoRecord, today: date) -> str:
    parts: list[str] = []
    try:
        scheduled = date.fromisoformat(todo.scheduled_date)
    except ValueError:
        scheduled = None
    if scheduled is not None and scheduled != today:
        parts.append(scheduled.strftime("%d %b"))
    if todo.reminder_time:
        parts.append(todo.reminder_time)
    return "  ".join(parts)


def _bucket(todo: TodoRecord, today: date) -> str:
    if todo.completed:
        return "Completed"
    if _state(todo, today) == "overdue":
        return "Overdue"
    try:
        scheduled = date.fromisoformat(todo.scheduled_date)
    except ValueError:
        return "Upcoming"
    if scheduled == today:
        return "Today"
    return "Upcoming"


def _ordered(todos: list[TodoRecord], today: date) -> list[TodoRecord]:
    def key(todo: TodoRecord) -> tuple:
        bucket = _bucket(todo, today)
        rank = {"Overdue": 0, "Today": 1, "Upcoming": 2, "Completed": 3}.get(bucket, 2)
        priority = {"high": 0, "normal": 1, "low": 2}.get(todo.priority, 1)
        return (rank, todo.scheduled_date, priority, todo.title.lower())

    return sorted(todos, key=key)


def _clock(value: str) -> tuple[int, int]:
    try:
        hour, minute = value.split(":", 1)
        return int(hour), int(minute)
    except (TypeError, ValueError):
        return 9, 0
