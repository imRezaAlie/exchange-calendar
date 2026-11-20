"""Timezone-aware dates, week boundaries, and compact Outlook Today labels."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

log = logging.getLogger(__name__)


def system_timezone() -> ZoneInfo:
    local = datetime.now().astimezone().tzinfo
    key = getattr(local, "key", None)
    if isinstance(key, str) and key:
        try:
            return ZoneInfo(key)
        except ZoneInfoNotFoundError:
            pass
    try:
        resolved = Path("/etc/localtime").resolve()
        parts = resolved.parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1 :])
            return ZoneInfo(name)
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    log.warning("The system timezone could not be resolved. Using UTC.")
    return ZoneInfo("UTC")


def resolve_timezone(name: str | None) -> ZoneInfo:
    cleaned = (name or "").strip()
    if cleaned.lower() in {"", "local", "system"}:
        return system_timezone()
    try:
        return ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        log.warning("Unknown timezone %s. Using the system timezone.", cleaned)
        return system_timezone()


def start_of_day(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def next_day(day: date, tz: ZoneInfo) -> datetime:
    return start_of_day(day + timedelta(days=1), tz)


def week_bounds(anchor: date, week_starts_on: str) -> tuple[date, date]:
    if week_starts_on == "sunday":
        delta = (anchor.weekday() + 1) % 7
    else:
        delta = anchor.weekday()
    start = anchor - timedelta(days=delta)
    return start, start + timedelta(days=6)


def month_bounds(anchor: date) -> tuple[date, date]:
    start = date(anchor.year, anchor.month, 1)
    if anchor.month == 12:
        following = date(anchor.year + 1, 1, 1)
    else:
        following = date(anchor.year, anchor.month + 1, 1)
    return start, following - timedelta(days=1)


def shift_month(anchor: date, steps: int) -> date:
    month_index = anchor.month - 1 + steps
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    last = month_bounds(date(year, month, 1))[1]
    return date(year, month, min(anchor.day, last.day))


def shift_anchor(anchor: date, view: str, steps: int) -> date:
    if view in {"weekly", "agenda"}:
        return anchor + timedelta(days=7 * steps)
    if view == "monthly":
        return shift_month(anchor, steps)
    return anchor + timedelta(days=steps)


def visible_days(anchor: date, view: str, week_starts_on: str) -> list[date]:
    if view == "daily":
        return [anchor]
    if view == "monthly":
        start, end = month_bounds(anchor)
    else:
        start, end = week_bounds(anchor, week_starts_on)
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def month_grid_days(anchor: date, week_starts_on: str) -> list[date]:
    """Full weeks covering the month, including leading and trailing dates."""
    start, end = month_bounds(anchor)
    grid_start, _grid_unused = week_bounds(start, week_starts_on)
    _week_start, grid_end = week_bounds(end, week_starts_on)
    days: list[date] = []
    current = grid_start
    while current <= grid_end:
        days.append(current)
        current += timedelta(days=1)
    return days


def stdlib_aware(value: datetime) -> datetime:
    """Copy an Exchange datetime into a normal datetime.

    EWSDateTime.astimezone() rejects the standard UTC timezone, so cache and
    conflict checks must not call it.
    """
    if type(value) is datetime:
        return value
    wall = datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
    )
    offset = value.utcoffset()
    if offset is None:
        return wall
    return (wall - offset).replace(tzinfo=timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Absolute instant. Direct ``<`` is wrong during a daylight-saving fold."""
    value = stdlib_aware(value)
    if value.tzinfo is None:
        raise ValueError("Timezone-aware datetimes are required.")
    return value.astimezone(timezone.utc)


def intersects(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> bool:
    return as_utc(start) < as_utc(window_end) and as_utc(end) > as_utc(window_start)


def intersects_day(start: datetime, end: datetime, day: date, tz: ZoneInfo) -> bool:
    return intersects(start, end, start_of_day(day, tz), next_day(day, tz))


def format_long_date(day: date) -> str:
    return f"{day.strftime('%A')}, {day.strftime('%B')} {day.day}, {day.year}"


def format_week_span(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%B')} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return f"{start.strftime('%B')} {start.day} – {end.strftime('%B')} {end.day}, {start.year}"
    return f"{format_long_date(start)} – {format_long_date(end)}"


def format_clock(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%H:%M")


def format_time_span(start: datetime, end: datetime, tz: ZoneInfo, all_day: bool = False) -> str:
    if all_day:
        return "All day"
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    text = f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}"
    if local_end.date() > local_start.date():
        extra_days = (local_end.date() - local_start.date()).days
        text += " +1" if extra_days == 1 else f" +{extra_days}"
    return text


def format_minutes(minutes: int) -> str:
    if minutes == 1:
        return "1 minute"
    if minutes < 60:
        return f"{minutes} minutes"
    hours, remainder = divmod(minutes, 60)
    hour_text = "1 hour" if hours == 1 else f"{hours} hours"
    if remainder == 0:
        return hour_text
    minute_text = "1 minute" if remainder == 1 else f"{remainder} minutes"
    return f"{hour_text} {minute_text}"


def summary_text(period_label: str, meeting_count: int, conflict_count: int) -> str:
    meetings = "1 Meeting" if meeting_count == 1 else f"{meeting_count} Meetings"
    if conflict_count == 0:
        conflicts = "No conflicts"
    elif conflict_count == 1:
        conflicts = "1 Conflicting Meeting"
    else:
        conflicts = f"{conflict_count} Conflicting Meetings"
    return f"{period_label}: {meetings} | {conflicts}"


def sync_window(anchor: date, tz: ZoneInfo, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Bounded fetch window around today and the date the user is viewing."""
    today = (now or datetime.now(tz)).astimezone(tz).date()
    start_day = min(today, anchor) - timedelta(days=30)
    end_day = max(today, anchor) + timedelta(days=60)
    if (end_day - start_day).days > 200:
        start_day = anchor - timedelta(days=14)
        end_day = anchor + timedelta(days=21)
    return start_of_day(start_day, tz), next_day(end_day, tz)


def period_label(anchor: date, view: str, week_starts_on: str, today: date) -> str:
    if view == "daily":
        return "Today" if anchor == today else format_long_date(anchor)
    if view == "monthly":
        return anchor.strftime("%B %Y")
    start, end = week_bounds(anchor, week_starts_on)
    if start <= today <= end:
        return "This Week"
    return f"Week of {start.strftime('%B')} {start.day}, {start.year}"
