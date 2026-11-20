"""Local tasks and the reminder ledger. Nothing here is sent to Exchange."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

from app.services.alarms import SnoozeRecord, TodoRecord

log = logging.getLogger(__name__)


class ReminderStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.todos_path = directory / "todos.json"
        self.state_path = directory / "alarms.json"
        self.todos: list[TodoRecord] = []
        self.fired: set[str] = set()
        self.snoozes: list[SnoozeRecord] = []
        self.load()

    def load(self) -> None:
        self.todos = [_todo for _todo in (_record(TodoRecord, item) for item in _read_list(self.todos_path)) if _todo.uid]
        payload = _read_object(self.state_path)
        fired = payload.get("fired") if isinstance(payload.get("fired"), list) else []
        self.fired = {str(item) for item in fired if item}
        snoozes = payload.get("snoozes") if isinstance(payload.get("snoozes"), list) else []
        self.snoozes = [record for record in (_record(SnoozeRecord, item) for item in snoozes) if record.key]

    def save(self) -> None:
        _write(self.todos_path, [todo.to_dict() for todo in self.todos])
        _write(
            self.state_path,
            {"fired": sorted(self.fired)[-500:], "snoozes": [item.to_dict() for item in self.snoozes]},
        )

    def add_todo(self, title: str, scheduled_date: str, reminder_time: str, priority: str) -> TodoRecord:
        todo = TodoRecord(
            uid=uuid.uuid4().hex,
            title=title.strip() or "Task",
            scheduled_date=scheduled_date,
            reminder_time=reminder_time.strip(),
            priority=priority if priority in {"high", "normal", "low"} else "normal",
        )
        self.todos.append(todo)
        self.save()
        return todo

    def replace_todos(self, todos: list[TodoRecord]) -> None:
        self.todos = list(todos)
        self.save()

    def update_todo(self, uid: str, title: str, scheduled_date: str, reminder_time: str, priority: str) -> None:
        for todo in self.todos:
            if todo.uid != uid:
                continue
            rescheduled = todo.scheduled_date != scheduled_date or todo.reminder_time != reminder_time
            if todo.scheduled_date != scheduled_date:
                todo.carried = False
            todo.title = title.strip() or "Task"
            todo.scheduled_date = scheduled_date
            todo.reminder_time = reminder_time.strip()
            todo.priority = priority if priority in {"high", "normal", "low"} else "normal"
            if rescheduled:
                self.snoozes = [item for item in self.snoozes if item.source_id != uid]
            break
        self.save()

    def complete(self, uid: str) -> None:
        for todo in self.todos:
            if todo.uid == uid:
                todo.completed = True
        self.snoozes = [item for item in self.snoozes if item.source_id != uid]
        self.save()

    def delete(self, uid: str) -> None:
        self.todos = [todo for todo in self.todos if todo.uid != uid]
        self.snoozes = [item for item in self.snoozes if item.source_id != uid]
        self.save()

    def mark_fired(self, keys: list[str]) -> None:
        self.fired.update(key for key in keys if key)
        fired_snoozes = set(keys)
        self.snoozes = [item for item in self.snoozes if item.key not in fired_snoozes]
        self.save()

    def add_snooze(self, record: SnoozeRecord) -> None:
        if any(item.key == record.key for item in self.snoozes):
            return
        self.snoozes.append(record)
        self.save()


def _record(cls, payload):
    if not isinstance(payload, dict):
        return cls.from_dict({})
    return cls.from_dict(payload)


def _read_list(path: Path) -> list:
    payload = _read_object(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    return []


def _read_object(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("Could not read %s.", path.name)
        return {}


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
