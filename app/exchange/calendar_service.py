"""Map Exchange calendar items into application records.

The inbox and the tasks folder are never opened. Calendar access is a read of
the occurrence view only: no item is created, changed, accepted, declined, or deleted.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.calendar.date_utils import stdlib_aware
from app.calendar.links import find_meeting_url
from app.models import Attendee, Meeting
from app.html_text import html_to_text

log = logging.getLogger(__name__)

_CALENDAR_FIELDS = (
    "subject",
    "start",
    "end",
    "location",
    "organizer",
    "required_attendees",
    "optional_attendees",
    "body",
    "legacy_free_busy_status",
    "my_response_type",
    "is_all_day",
    "is_cancelled",
    "is_recurring",
    "type",
    "uid",
    "meeting_workspace_url",
    "net_show_url",
    "is_online_meeting",
    "reminder_is_set",
    "reminder_minutes_before_start",
)


def normalize_response(value: str | None) -> str:
    key = (value or "").strip().lower().replace(" ", "").replace("_", "")
    mapping = {
        "accept": "accepted",
        "accepted": "accepted",
        "decline": "declined",
        "declined": "declined",
        "tentative": "tentative",
        "tentativelyaccept": "tentative",
        "unknown": "unknown",
        "organizer": "organizer",
        "noresponsereceived": "not_responded",
        "notresponded": "not_responded",
        "none": "none",
    }
    return mapping.get(key, "unknown")


def normalize_busy(value: str | None) -> str:
    key = (value or "").strip().lower().replace(" ", "").replace("_", "")
    mapping = {
        "free": "free",
        "tentative": "tentative",
        "busy": "busy",
        "oof": "oof",
        "outofoffice": "oof",
        "workingelsewhere": "working_elsewhere",
        "nodata": "no_data",
        "": "no_data",
    }
    return mapping.get(key, "busy")


def _clean_url(url: str) -> str:
    return url.rstrip(").,]>\"'")


def extract_online_meeting_url(item) -> str | None:
    for attribute in ("meeting_workspace_url", "net_show_url", "join_online_meeting_url"):
        value = getattr(item, attribute, None)
        if value and str(value).startswith(("http://", "https://")):
            return _clean_url(str(value))
    location = str(getattr(item, "location", "") or "")
    body = str(getattr(item, "body", "") or "")
    return find_meeting_url(location, body)


def _people(values, required: bool) -> list[Attendee]:
    people: list[Attendee] = []
    for value in values or []:
        mailbox = getattr(value, "mailbox", value)
        name = str(getattr(mailbox, "name", "") or "")
        email = str(getattr(mailbox, "email_address", "") or "")
        response = normalize_response(str(getattr(value, "response_type", "") or "unknown"))
        if not name and not email:
            continue
        people.append(Attendee(name=name or email, email=email, required=required, response=response))
    return people


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        plain = stdlib_aware(value)
        if plain.tzinfo is None:
            return plain.replace(tzinfo=timezone.utc)
        return plain
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return _as_datetime(datetime.fromisoformat(value.isoformat()))
        except (TypeError, ValueError):
            return None
    return None


def _normalize_all_day(start: datetime, end: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    day = local_start.date()
    if local_end.time() == time.min and local_end.date() > day:
        end_day = local_end.date()
    else:
        end_day = local_end.date() + timedelta(days=1)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(end_day, time.min, tzinfo=tz)
    if end_local <= start_local:
        end_local = start_local + timedelta(days=1)
    return start_local, end_local


def map_calendar_item(item, mailbox: str, tz: ZoneInfo) -> Meeting | None:
    if getattr(item, "type", None) == "RecurringMaster":
        return None
    start = _as_datetime(getattr(item, "start", None))
    end = _as_datetime(getattr(item, "end", None))
    if start is None or end is None:
        return None
    is_all_day = bool(getattr(item, "is_all_day", False))
    if is_all_day:
        start, end = _normalize_all_day(start, end, tz)
    identifier = getattr(item, "id", None)
    ews_id = getattr(identifier, "id", None) if identifier is not None else None
    uid = str(ews_id or f"{getattr(item, 'uid', 'item')}:{start.isoformat()}")
    organizer = getattr(item, "organizer", None)
    body = getattr(item, "body", None)
    body_text_raw = str(body or "")
    body_type = str(getattr(body, "body_type", "") or "")
    if body_type.upper() == "HTML" or "<" in body_text_raw[:200]:
        body_html = body_text_raw
        plain = html_to_text(body_text_raw)
    else:
        body_html = ""
        plain = body_text_raw
    item_type = str(getattr(item, "type", "") or "")
    is_recurring = bool(getattr(item, "is_recurring", False)) or item_type in {"Occurrence", "Exception"}
    series_id = str(getattr(item, "uid", "") or "") if is_recurring else None
    return Meeting(
        uid=uid,
        subject=str(getattr(item, "subject", "") or ""),
        start=start,
        end=end,
        organizer_name=str(getattr(organizer, "name", "") or ""),
        organizer_email=str(getattr(organizer, "email_address", "") or ""),
        required_attendees=_people(getattr(item, "required_attendees", None), True),
        optional_attendees=_people(getattr(item, "optional_attendees", None), False),
        location=str(getattr(item, "location", "") or ""),
        body_html=body_html,
        body_text=plain,
        busy_status=normalize_busy(getattr(item, "legacy_free_busy_status", None)),
        response_status=normalize_response(getattr(item, "my_response_type", None)),
        online_meeting_url=extract_online_meeting_url(item),
        is_all_day=is_all_day,
        is_cancelled=bool(getattr(item, "is_cancelled", False)),
        is_recurring=is_recurring,
        series_id=series_id or None,
        mailbox=mailbox,
        reminder_minutes=_exchange_reminder(item),
    )


def _exchange_reminder(item) -> int | None:
    if not hasattr(item, "reminder_is_set") and not hasattr(item, "reminder_minutes_before_start"):
        return None
    if getattr(item, "reminder_is_set", None) is False:
        return -1
    minutes = getattr(item, "reminder_minutes_before_start", None)
    if minutes is None:
        return None
    try:
        return int(minutes)
    except (TypeError, ValueError):
        return None


def _unique(meetings: list[Meeting]) -> list[Meeting]:
    seen: set[str] = set()
    unique: list[Meeting] = []
    for meeting in meetings:
        uid = meeting.uid
        if uid in seen:
            uid = f"{uid}|{meeting.start.isoformat()}"
            meeting.uid = uid
        seen.add(meeting.uid)
        unique.append(meeting)
    return unique


def fetch_meetings(account, start: datetime, end: datetime, mailbox: str, tz: ZoneInfo) -> list[Meeting]:
    """Read calendar occurrences. This does not write to the mailbox."""
    queryset = account.calendar.view(start=start, end=end)
    try:
        items = list(queryset.only(*_CALENDAR_FIELDS))
    except Exception:
        log.info("The server rejected a narrow calendar field list. Requesting the default fields.")
        items = list(queryset)
    meetings: list[Meeting] = []
    for item in items:
        try:
            mapped = map_calendar_item(item, mailbox, tz)
        except Exception:
            log.warning("A calendar item was skipped because it could not be read.")
            continue
        if mapped is not None:
            meetings.append(mapped)
    return _unique(meetings)
