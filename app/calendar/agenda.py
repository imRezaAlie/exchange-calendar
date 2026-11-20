"""Current meeting and the next one. Read-only; nothing is written to Exchange."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.calendar.date_utils import as_utc, format_minutes
from app.models import Meeting


def agenda_at(meetings: list[Meeting], now: datetime) -> tuple[Meeting | None, Meeting | None]:
    """Latest meeting already underway, then the earliest one that has not started."""
    moment = as_utc(now)
    eligible = [meeting for meeting in meetings if _counts(meeting)]
    current_ones = [
        meeting
        for meeting in eligible
        if as_utc(meeting.start) <= moment < as_utc(meeting.end)
    ]
    current_ones.sort(key=lambda meeting: (as_utc(meeting.start), as_utc(meeting.end), meeting.subject.lower()))
    current = current_ones[-1] if current_ones else None
    upcoming_ones = [meeting for meeting in eligible if as_utc(meeting.start) > moment]
    upcoming_ones.sort(key=lambda meeting: (as_utc(meeting.start), meeting.subject.lower()))
    upcoming = upcoming_ones[0] if upcoming_ones else None
    return current, upcoming


def until_text(moment: datetime, now: datetime, tz) -> str:
    local = moment.astimezone(tz)
    clock = local.strftime("%H:%M")
    today = now.astimezone(tz).date()
    if local.date() == today:
        return f"until {clock}"
    if local.date() == today + timedelta(days=1):
        return f"until tomorrow {clock}"
    return f"until {local.strftime('%a')} {clock}"


def starts_text(start: datetime, now: datetime, tz) -> str:
    local = start.astimezone(tz)
    minutes = int((as_utc(start) - as_utc(now)).total_seconds() // 60)
    if minutes < 1:
        lead = "starting"
    elif minutes == 1:
        lead = "in 1 min"
    elif minutes < 60:
        lead = f"in {minutes} min"
    else:
        lead = f"in {format_minutes(minutes)}"
    clock = local.strftime("%H:%M")
    today = now.astimezone(tz).date()
    if local.date() == today:
        return f"{lead} · {clock}"
    if local.date() == today + timedelta(days=1):
        return f"{lead} · tomorrow {clock}"
    return f"{lead} · {local.strftime('%a')} {clock}"


def _counts(meeting: Meeting) -> bool:
    if meeting.is_cancelled or meeting.is_all_day:
        return False
    if meeting.response_status == "declined" or meeting.busy_status == "free":
        return False
    return True
