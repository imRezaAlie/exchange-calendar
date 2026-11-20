"""Calendar and task records shared by the UI, cache, and Exchange client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.calendar.date_utils import as_utc


def to_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat()


def _reminder_minutes(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def from_utc_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(slots=True)
class Attendee:
    name: str
    email: str = ""
    required: bool = True
    response: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
            "required": self.required,
            "response": self.response,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> Attendee:
        return cls(
            name=str(payload.get("name") or ""),
            email=str(payload.get("email") or ""),
            required=bool(payload.get("required", True)),
            response=str(payload.get("response") or "unknown"),
        )


@dataclass(slots=True)
class Meeting:
    uid: str
    subject: str
    start: datetime
    end: datetime
    organizer_name: str = ""
    organizer_email: str = ""
    required_attendees: list[Attendee] = field(default_factory=list)
    optional_attendees: list[Attendee] = field(default_factory=list)
    location: str = ""
    body_html: str = ""
    body_text: str = ""
    busy_status: str = "busy"
    response_status: str = "accepted"
    online_meeting_url: str | None = None
    is_all_day: bool = False
    is_cancelled: bool = False
    is_recurring: bool = False
    series_id: str | None = None
    mailbox: str = ""
    reminder_minutes: int | None = None

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "subject": self.subject,
            "start": to_utc_iso(self.start),
            "end": to_utc_iso(self.end),
            "organizer_name": self.organizer_name,
            "organizer_email": self.organizer_email,
            "required_attendees": [item.to_dict() for item in self.required_attendees],
            "optional_attendees": [item.to_dict() for item in self.optional_attendees],
            "location": self.location,
            "body_html": self.body_html,
            "body_text": self.body_text,
            "busy_status": self.busy_status,
            "response_status": self.response_status,
            "online_meeting_url": self.online_meeting_url,
            "is_all_day": self.is_all_day,
            "is_cancelled": self.is_cancelled,
            "is_recurring": self.is_recurring,
            "series_id": self.series_id,
            "mailbox": self.mailbox,
            "reminder_minutes": self.reminder_minutes,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> Meeting:
        start = from_utc_iso(payload.get("start"))
        end = from_utc_iso(payload.get("end"))
        if start is None or end is None:
            raise ValueError("A cached meeting is missing its start or end time.")
        return cls(
            uid=str(payload.get("uid") or ""),
            subject=str(payload.get("subject") or ""),
            start=start,
            end=end,
            organizer_name=str(payload.get("organizer_name") or ""),
            organizer_email=str(payload.get("organizer_email") or ""),
            required_attendees=[
                Attendee.from_dict(item) for item in payload.get("required_attendees") or []
            ],
            optional_attendees=[
                Attendee.from_dict(item) for item in payload.get("optional_attendees") or []
            ],
            location=str(payload.get("location") or ""),
            body_html=str(payload.get("body_html") or ""),
            body_text=str(payload.get("body_text") or ""),
            busy_status=str(payload.get("busy_status") or "busy"),
            response_status=str(payload.get("response_status") or "unknown"),
            online_meeting_url=payload.get("online_meeting_url") or None,
            is_all_day=bool(payload.get("is_all_day", False)),
            is_cancelled=bool(payload.get("is_cancelled", False)),
            is_recurring=bool(payload.get("is_recurring", False)),
            series_id=payload.get("series_id") or None,
            mailbox=str(payload.get("mailbox") or ""),
            reminder_minutes=_reminder_minutes(payload.get("reminder_minutes")),
        )


@dataclass(slots=True)
class TaskItem:
    uid: str
    subject: str
    due: datetime | None = None
    is_complete: bool = False
    importance: str = "normal"
    mailbox: str = ""

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "subject": self.subject,
            "due": to_utc_iso(self.due),
            "is_complete": self.is_complete,
            "importance": self.importance,
            "mailbox": self.mailbox,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> TaskItem:
        return cls(
            uid=str(payload.get("uid") or ""),
            subject=str(payload.get("subject") or ""),
            due=from_utc_iso(payload.get("due")),
            is_complete=bool(payload.get("is_complete", False)),
            importance=str(payload.get("importance") or "normal"),
            mailbox=str(payload.get("mailbox") or ""),
        )


@dataclass(slots=True)
class SyncSnapshot:
    """One calendar refresh, either live, cached, or generated for demo mode."""

    meetings: list[Meeting]
    tasks: list[TaskItem]
    tasks_state: str
    tasks_message: str
    connected: bool
    from_cache: bool
    synced_at: datetime | None
    error: str | None
    mailbox: str
    demo: bool
    window_start: datetime | None = None
    window_end: datetime | None = None
