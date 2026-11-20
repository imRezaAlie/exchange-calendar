"""Local tasks. Completion and deletion cancel their reminders."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTimeEdit,
    QVBoxLayout,
)

from app.ui.widgets import make_button

from app.services.alarms import TodoRecord
from app.storage.reminders import ReminderStore


class TodoDialog(QDialog):
    changed = Signal()

    def __init__(self, store: ReminderStore, today: date, default_time: str, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._today = today
        self.setWindowTitle("Tasks")
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)
        intro = QLabel("Reminders ring at the time you set. Unfinished tasks move to the next day.")
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        form = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Task")
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDate(QDate(today.year, today.month, today.day))
        self.clock = QTimeEdit()
        hour, minute = _clock(default_time)
        self.clock.setTime(QTime(hour, minute))
        self.remind = QCheckBox("Remind")
        self.remind.setChecked(True)
        self.remind.toggled.connect(self.clock.setEnabled)
        self.priority = QComboBox()
        self.priority.addItem("High", "high")
        self.priority.addItem("Normal", "normal")
        self.priority.addItem("Low", "low")
        self.priority.setCurrentIndex(1)
        form.addWidget(self.title, 1)
        form.addWidget(self.day)
        form.addWidget(self.remind)
        form.addWidget(self.clock)
        form.addWidget(self.priority)
        layout.addLayout(form)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        add = make_button("Add Task", "primary")
        add.setFixedWidth(112)
        add.clicked.connect(self._add)
        update = make_button("Update", "secondary")
        done = make_button("Mark as Done", "secondary")
        delete = make_button("Delete", "danger")
        for button in (update, done, delete):
            button.setFixedWidth(128)
        update.clicked.connect(self._update)
        done.clicked.connect(self._complete)
        delete.clicked.connect(self._delete)
        actions.addWidget(add)
        actions.addWidget(update)
        actions.addWidget(done)
        actions.addWidget(delete)
        actions.addStretch(1)
        close = make_button("Close", "secondary")
        close.setFixedWidth(96)
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.list.currentItemChanged.connect(self._load_selected)
        self.reload()

    def reload(self) -> None:
        self.list.clear()
        for todo in self.store.todos:
            item = QListWidgetItem(_label(todo))
            item.setData(Qt.ItemDataRole.UserRole, todo.uid)
            self.list.addItem(item)

    def select_uid(self, uid: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == uid:
                self.list.setCurrentItem(item)
                return

    def _add(self) -> None:
        title = self.title.text().strip()
        if not title:
            return
        chosen = self.day.date()
        self.store.add_todo(
            title,
            date(chosen.year(), chosen.month(), chosen.day()).isoformat(),
            self._reminder_time(),
            str(self.priority.currentData()),
        )
        self.title.clear()
        self.reload()
        self.changed.emit()

    def _reminder_time(self) -> str:
        if not self.remind.isChecked():
            return ""
        clock = self.clock.time()
        return f"{clock.hour():02d}:{clock.minute():02d}"

    def _load_selected(self, current, _previous) -> None:
        if current is None:
            return
        uid = str(current.data(Qt.ItemDataRole.UserRole) or "")
        todo = next((item for item in self.store.todos if item.uid == uid), None)
        if todo is None:
            return
        self.title.setText(todo.title)
        try:
            year, month, day = (int(part) for part in todo.scheduled_date.split("-"))
            self.day.setDate(QDate(year, month, day))
        except ValueError:
            pass
        if todo.reminder_time:
            hour, minute = _clock(todo.reminder_time)
            self.clock.setTime(QTime(hour, minute))
            self.remind.setChecked(True)
        else:
            self.remind.setChecked(False)
        index = self.priority.findData(todo.priority)
        if index >= 0:
            self.priority.setCurrentIndex(index)

    def _update(self) -> None:
        uid = self._selected()
        title = self.title.text().strip()
        if not uid or not title:
            return
        chosen = self.day.date()
        self.store.update_todo(
            uid,
            title,
            date(chosen.year(), chosen.month(), chosen.day()).isoformat(),
            self._reminder_time(),
            str(self.priority.currentData()),
        )
        self.reload()
        self.select_uid(uid)
        self.changed.emit()

    def _selected(self) -> str:
        item = self.list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _complete(self) -> None:
        uid = self._selected()
        if not uid:
            return
        self.store.complete(uid)
        self.reload()
        self.changed.emit()

    def _delete(self) -> None:
        uid = self._selected()
        if not uid:
            return
        self.store.delete(uid)
        self.reload()
        self.changed.emit()


def _clock(value: str) -> tuple[int, int]:
    try:
        hour, minute = value.split(":", 1)
        return int(hour), int(minute)
    except (TypeError, ValueError):
        return 9, 0


def _label(todo: TodoRecord) -> str:
    state = "Done" if todo.completed else todo.priority.capitalize()
    when = todo.reminder_time or "no reminder"
    return f"{todo.scheduled_date}  {when}  {state}  {todo.title}"
