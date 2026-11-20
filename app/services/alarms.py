"""Minute-accurate meeting and task reminders. No mailbox access and no audio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import ConflictPolicy, ConflictReport, detect_conflicts
from app.calendar.date_utils import as_utc
from app.models import Meeting

OFFSETS = (30, 15, 10, 5, 0)
SNOOZE_MINUTES = (5, 10, 15, 30)
DUE_WINDOW = timedelta(seconds=75)
RESUME_WINDOW = timedelta(minutes=3)


@dataclass(frozen=True)
class DueAlarm:
    key: str
    kind: str
    source_id: str
    title: str
    event_at: datetime
    trigger_at: datetime
    offset_minutes: int
    url: str = ""
    location: str = ""
    priority: str = ""
    conflict_name: str = ""
    conflict_minutes: int = 0
    cached: bool = False
    snoozed: bool = False

    @property
    def remaining_text(self) -> str:
        return remaining_text(self.event_at, self.trigger_at if self.snoozed else self.event_at, self.offset_minutes, self.snoozed)


def remaining_text(event_at: datetime, now: datetime, offset_minutes: int, snoozed: bool) -> str:
    if snoozed:
        return "Snoozed reminder"
    if offset_minutes <= 0:
        return "Starting now"
    if offset_minutes == 1:
        return "Starts in 1 minute"
    return f"Starts in {offset_minutes} minutes"


@dataclass
class TodoRecord:
    uid: str
    title: str
    scheduled_date: str
    reminder_time: str = ""
    priority: str = "normal"
    completed: bool = False
    notes: str = ""
    carried: bool = False

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "title": self.title,
            "scheduled_date": self.scheduled_date,
            "reminder_time": self.reminder_time,
            "priority": self.priority,
            "completed": self.completed,
            "notes": self.notes,
            "carried": self.carried,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> TodoRecord:
        return cls(
            uid=str(payload.get("uid") or ""),
            title=str(payload.get("title") or ""),
            scheduled_date=str(payload.get("scheduled_date") or ""),
            reminder_time=str(payload.get("reminder_time") or ""),
            priority=str(payload.get("priority") or "normal"),
            completed=bool(payload.get("completed", False)),
            notes=str(payload.get("notes") or ""),
            carried=bool(payload.get("carried", False)),
        )


@dataclass
class SnoozeRecord:
    key: str
    kind: str
    source_id: str
    title: str
    event_at: str
    trigger_at: str
    url: str = ""
    location: str = ""
    priority: str = ""
    conflict_name: str = ""
    conflict_minutes: int = 0
    cached: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "source_id": self.source_id,
            "title": self.title,
            "event_at": self.event_at,
            "trigger_at": self.trigger_at,
            "url": self.url,
            "location": self.location,
            "priority": self.priority,
            "conflict_name": self.conflict_name,
            "conflict_minutes": self.conflict_minutes,
            "cached": self.cached,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> SnoozeRecord:
        return cls(
            key=str(payload.get("key") or ""),
            kind=str(payload.get("kind") or "meeting"),
            source_id=str(payload.get("source_id") or ""),
            title=str(payload.get("title") or ""),
            event_at=str(payload.get("event_at") or ""),
            trigger_at=str(payload.get("trigger_at") or ""),
            url=str(payload.get("url") or ""),
            location=str(payload.get("location") or ""),
            priority=str(payload.get("priority") or ""),
            conflict_name=str(payload.get("conflict_name") or ""),
            conflict_minutes=int(payload.get("conflict_minutes") or 0),
            cached=bool(payload.get("cached", False)),
        )


def normalize_offsets(value: object, fallback: list[int] | None = None) -> list[int]:
    allowed = set(OFFSETS) | {2}
    found: list[int] = []
    if isinstance(value, list):
        for item in value:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number in allowed and number not in found:
                found.append(number)
    elif fallback:
        return list(fallback)
    found.sort(reverse=True)
    return found


def meeting_offsets(meeting: Meeting, configured: list[int], respect_exchange: bool) -> list[int]:
    """Use the Exchange lead time only when the item actually carried one."""
    stored = getattr(meeting, "reminder_minutes", None)
    if respect_exchange and stored is not None:
        if int(stored) < 0:
            return []
        return normalize_offsets([stored])
    return normalize_offsets(configured)


def meeting_key(meeting: Meeting, offset: int) -> str:
    return f"meeting|{meeting.uid}|{as_utc(meeting.start).isoformat()}|{int(offset)}"


def todo_key(todo: TodoRecord) -> str:
    return f"todo|{todo.uid}|{todo.scheduled_date}|{todo.reminder_time}"


def summary_key(day: date) -> str:
    return f"summary|{day.isoformat()}"


def snooze_key(source_id: str, trigger: datetime) -> str:
    return f"snooze|{source_id}|{as_utc(trigger).isoformat()}"


def _eligible_meeting(meeting: Meeting) -> bool:
    if meeting.is_cancelled or meeting.is_all_day:
        return False
    if meeting.response_status == "declined" or meeting.busy_status == "free":
        return False
    return True


def _in_window(trigger: datetime, now: datetime, latest: datetime | None) -> bool:
    moment = as_utc(now)
    start = as_utc(trigger)
    if moment < start:
        return False
    if latest is not None and moment >= as_utc(latest):
        return False
    return moment < start + RESUME_WINDOW


def carry_forward(todos: list[TodoRecord], today: date, enabled: bool) -> bool:
    """Move unfinished tasks onto today. Reminder clocks stay on the new date."""
    if not enabled:
        return False
    changed = False
    for todo in todos:
        if todo.completed or not todo.scheduled_date:
            continue
        try:
            scheduled = date.fromisoformat(todo.scheduled_date)
        except ValueError:
            continue
        if scheduled < today:
            todo.scheduled_date = today.isoformat()
            todo.carried = True
            changed = True
    return changed


def due_meeting_alarms(
    meetings: list[Meeting],
    now: datetime,
    offsets: list[int],
    fired: set[str],
    *,
    respect_exchange: bool = False,
    conflict_warnings: bool = True,
    conflict_policy: ConflictPolicy | None = None,
    cached: bool = False,
) -> list[DueAlarm]:
    report = ConflictReport()
    by_id = {meeting.uid: meeting for meeting in meetings}
    if conflict_warnings:
        report = detect_conflicts(meetings, conflict_policy or ConflictPolicy())
    alarms: list[DueAlarm] = []
    for meeting in meetings:
        if not _eligible_meeting(meeting):
            continue
        for offset in meeting_offsets(meeting, offsets, respect_exchange):
            key = meeting_key(meeting, offset)
            if key in fired:
                continue
            trigger = meeting.start - timedelta(minutes=offset)
            if not _in_window(trigger, now, meeting.end):
                continue
            conflict_name, conflict_minutes = _conflict_for(meeting, report, by_id) if conflict_warnings else ("", 0)
            alarms.append(
                DueAlarm(
                    key=key,
                    kind="meeting",
                    source_id=meeting.uid,
                    title=(meeting.subject or "").strip() or "(No subject)",
                    event_at=meeting.start,
                    trigger_at=trigger,
                    offset_minutes=offset,
                    url=_meeting_url(meeting),
                    location=(meeting.location or "").strip(),
                    conflict_name=conflict_name,
                    conflict_minutes=conflict_minutes,
                    cached=cached,
                )
            )
    alarms.sort(key=lambda item: (as_utc(item.trigger_at), item.title.lower()))
    return alarms


def due_todo_alarms(
    todos: list[TodoRecord],
    now: datetime,
    tz: ZoneInfo,
    fired: set[str],
    *,
    enabled: bool = True,
    overdue: bool = True,
) -> list[DueAlarm]:
    if not enabled:
        return []
    local_now = now.astimezone(tz)
    alarms: list[DueAlarm] = []
    for todo in todos:
        if todo.completed or not todo.reminder_time or not todo.scheduled_date:
            continue
        trigger = _todo_trigger(todo, tz)
        if trigger is None:
            continue
        key = todo_key(todo)
        if key in fired:
            continue
        if local_now.date().isoformat() != todo.scheduled_date:
            continue
        if as_utc(local_now) < as_utc(trigger):
            continue
        on_time = as_utc(local_now) < as_utc(trigger) + RESUME_WINDOW
        if not on_time and not overdue:
            continue
        if not on_time and local_now.date() != trigger.astimezone(tz).date():
            continue
        alarms.append(
            DueAlarm(
                key=key,
                kind="todo",
                source_id=todo.uid,
                title=todo.title.strip() or "(No title)",
                event_at=trigger,
                trigger_at=trigger,
                offset_minutes=0,
                priority=todo.priority or "normal",
            )
        )
    alarms.sort(key=lambda item: item.title.lower())
    return alarms


def due_summary(
    todos: list[TodoRecord],
    now: datetime,
    tz: ZoneInfo,
    fired: set[str],
    *,
    enabled: bool,
) -> DueAlarm | None:
    if not enabled:
        return None
    local = now.astimezone(tz)
    trigger = datetime.combine(local.date(), time(8, 0), tzinfo=tz)
    key = summary_key(local.date())
    if key in fired or as_utc(local) < as_utc(trigger) or as_utc(local) > as_utc(trigger) + timedelta(hours=4):
        return None
    open_items = [todo for todo in todos if not todo.completed and todo.scheduled_date == local.date().isoformat()]
    if not open_items:
        return None
    title = f"{len(open_items)} task" if len(open_items) == 1 else f"{len(open_items)} tasks"
    return DueAlarm(
        key=key,
        kind="summary",
        source_id=key,
        title=f"Today: {title}",
        event_at=trigger,
        trigger_at=trigger,
        offset_minutes=0,
        location="; ".join(todo.title for todo in open_items[:6]),
    )


def due_snoozes(snoozes: list[SnoozeRecord], now: datetime, fired: set[str]) -> list[DueAlarm]:
    alarms: list[DueAlarm] = []
    for record in snoozes:
        if not record.key or record.key in fired:
            continue
        trigger = _parse(record.trigger_at)
        event = _parse(record.event_at) or trigger
        if trigger is None or event is None:
            continue
        if not _in_window(trigger, now, trigger + timedelta(hours=12)):
            continue
        alarms.append(
            DueAlarm(
                key=record.key,
                kind=record.kind,
                source_id=record.source_id,
                title=record.title or "(Reminder)",
                event_at=event,
                trigger_at=trigger,
                offset_minutes=0,
                url=record.url,
                location=record.location,
                priority=record.priority,
                conflict_name=record.conflict_name,
                conflict_minutes=record.conflict_minutes,
                cached=record.cached,
                snoozed=True,
            )
        )
    return alarms


def make_snooze(alarm: DueAlarm, minutes: int, now: datetime) -> SnoozeRecord:
    trigger = now + timedelta(minutes=minutes)
    return SnoozeRecord(
        key=snooze_key(alarm.source_id or alarm.key, trigger),
        kind=alarm.kind if alarm.kind in {"meeting", "todo"} else "meeting",
        source_id=alarm.source_id,
        title=alarm.title,
        event_at=as_utc(alarm.event_at).isoformat(),
        trigger_at=as_utc(trigger).isoformat(),
        url=alarm.url,
        location=alarm.location,
        priority=alarm.priority,
        conflict_name=alarm.conflict_name,
        conflict_minutes=alarm.conflict_minutes,
        cached=alarm.cached,
    )


def next_trigger(
    meetings: list[Meeting],
    todos: list[TodoRecord],
    snoozes: list[SnoozeRecord],
    now: datetime,
    tz: ZoneInfo,
    offsets: list[int],
    fired: set[str],
) -> datetime | None:
    candidates: list[datetime] = []
    moment = as_utc(now)
    for meeting in meetings:
        if not _eligible_meeting(meeting):
            continue
        for offset in meeting_offsets(meeting, offsets, False):
            if meeting_key(meeting, offset) in fired:
                continue
            trigger = as_utc(meeting.start - timedelta(minutes=offset))
            if trigger >= moment:
                candidates.append(trigger)
    for todo in todos:
        if todo.completed:
            continue
        trigger = _todo_trigger(todo, tz)
        if trigger is None or todo_key(todo) in fired:
            continue
        instant = as_utc(trigger)
        if instant >= moment:
            candidates.append(instant)
    for record in snoozes:
        trigger = _parse(record.trigger_at)
        if trigger is None or record.key in fired:
            continue
        instant = as_utc(trigger)
        if instant >= moment:
            candidates.append(instant)
    if not candidates:
        return None
    return min(candidates)


def drop_snoozes_for(snoozes: list[SnoozeRecord], source_id: str) -> list[SnoozeRecord]:
    return [record for record in snoozes if record.source_id != source_id]


def _conflict_for(meeting: Meeting, report: ConflictReport, by_id: dict[str, Meeting]) -> tuple[str, int]:
    overlaps = report.for_meeting(meeting.uid)
    if not overlaps:
        return "", 0
    largest = max(overlaps, key=lambda item: (item.minutes, as_utc(item.start)))
    other = by_id.get(largest.other(meeting.uid))
    name = ((other.subject if other else "") or "another meeting").strip()
    return name, largest.minutes


def _meeting_url(meeting: Meeting) -> str:
    from app.calendar.links import meeting_url

    return meeting_url(meeting)


def _todo_trigger(todo: TodoRecord, tz: ZoneInfo) -> datetime | None:
    try:
        day = date.fromisoformat(todo.scheduled_date)
        hour, minute = todo.reminder_time.split(":", 1)
        clock = time(int(hour), int(minute))
    except (TypeError, ValueError):
        return None
    return datetime.combine(day, clock, tzinfo=tz)


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
