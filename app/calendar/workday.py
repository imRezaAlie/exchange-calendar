"""Busy and free time inside the 08:00–18:00 Tehran workday."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.calendar.date_utils import as_utc, week_bounds
from app.models import Meeting

TEHRAN = ZoneInfo("Asia/Tehran")
WORK_START = time(8, 0)
WORK_END = time(18, 0)
WORK_MINUTES = 10 * 60
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class WorkdayLoad:
    def __init__(self, busy_minutes: int) -> None:
        self.busy_minutes = busy_minutes
        self.free_minutes = WORK_MINUTES - busy_minutes


@dataclass(frozen=True, slots=True)
class FreeBlock:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return _minutes_between(as_utc(self.start), as_utc(self.end))


def workday_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, WORK_START, tzinfo=TEHRAN)
    end = datetime.combine(day, WORK_END, tzinfo=TEHRAN)
    return start, end


def occupies_workday(meeting: Meeting) -> bool:
    """Timed meetings you are still expected to attend."""
    if meeting.is_cancelled or meeting.is_all_day:
        return False
    if meeting.response_status == "declined" or meeting.busy_status == "free":
        return False
    return True


def workday_load(meetings: list[Meeting], day: date) -> WorkdayLoad:
    """Minutes inside 08:00–18:00 Tehran. Overlaps are counted once."""
    return WorkdayLoad(_merged_minutes(_clipped_busy(meetings, day)))


def free_blocks(
    meetings: list[Meeting],
    day: date,
    *,
    now: datetime | None = None,
    minimum_minutes: int = 15,
) -> list[FreeBlock]:
    """Open intervals inside the workday. Time already passed today is omitted."""
    window_start, window_end = workday_bounds(day)
    cursor = window_start
    if now is not None:
        local_now = as_utc(now).astimezone(TEHRAN)
        if local_now.date() > day or (local_now.date() == day and local_now >= window_end):
            return []
        if local_now.date() == day and local_now > window_start:
            cursor = _ceil_minute(local_now)
            if cursor >= window_end:
                return []
    blocks: list[FreeBlock] = []
    for start, end in _clipped_busy(meetings, day):
        local_start = start.astimezone(TEHRAN)
        local_end = end.astimezone(TEHRAN)
        if local_end <= cursor:
            continue
        if local_start > cursor:
            blocks.append(FreeBlock(cursor, min(local_start, window_end)))
        cursor = max(cursor, local_end)
        if cursor >= window_end:
            break
    if cursor < window_end:
        blocks.append(FreeBlock(cursor, window_end))
    return [block for block in blocks if block.minutes >= minimum_minutes]


def next_opening(
    meetings: list[Meeting],
    now: datetime,
    minimum_minutes: int,
    week_starts_on: str = "monday",
) -> FreeBlock | None:
    """First remaining opening of the requested length through the end of this week."""
    today = as_utc(now).astimezone(TEHRAN).date()
    _week_start, week_end = week_bounds(today, week_starts_on)
    day = today + timedelta(days=1)
    while day <= week_end:
        found = free_blocks(meetings, day, now=now, minimum_minutes=minimum_minutes)
        if found:
            return found[0]
        day += timedelta(days=1)
    return None


def format_span(block: FreeBlock) -> str:
    return f"{block.start.strftime('%H:%M')}–{block.end.strftime('%H:%M')}"


def format_opening(block: FreeBlock, today: date) -> str:
    day = block.start.astimezone(TEHRAN).date()
    if day == today + timedelta(days=1):
        when = "Tomorrow"
    else:
        when = _WEEKDAYS[day.weekday()]
    return f"{when} {format_span(block)}"


def open_time_summary(
    meetings: list[Meeting],
    now: datetime,
    week_starts_on: str = "monday",
) -> tuple[str, str]:
    """Today's remaining openings, then the next 30- and 60-minute gap this week."""
    today = as_utc(now).astimezone(TEHRAN).date()
    blocks = free_blocks(meetings, today, now=now)
    today_text = " · ".join(format_span(block) for block in blocks) or "No open time left"
    has_30 = any(block.minutes >= 30 for block in blocks)
    has_60 = any(block.minutes >= 60 for block in blocks)
    if has_30 and has_60:
        return today_text, ""
    parts: list[str] = []
    if not has_30:
        short = next_opening(meetings, now, 30, week_starts_on)
        long = next_opening(meetings, now, 60, week_starts_on)
        if short is None:
            return today_text, "No 30m opening left this week"
        if long is not None and (short.start, short.end) == (long.start, long.end):
            return today_text, f"60m {format_opening(long, today)}"
        parts.append(f"30m {format_opening(short, today)}")
        if long is None:
            parts.append("No 60m opening left this week")
        else:
            parts.append(f"60m {format_opening(long, today)}")
        return today_text, " · ".join(parts)
    long = next_opening(meetings, now, 60, week_starts_on)
    if long is None:
        return today_text, "No 60m opening left this week"
    return today_text, f"60m {format_opening(long, today)}"


def format_hours(minutes: int) -> str:
    hours, remainder = divmod(max(0, int(minutes)), 60)
    if remainder == 0:
        return f"{hours}h"
    if hours == 0:
        return f"{remainder}m"
    return f"{hours}h {remainder}m"


def _clipped_busy(meetings: list[Meeting], day: date) -> list[tuple[datetime, datetime]]:
    window_start, window_end = workday_bounds(day)
    clipped: list[tuple[datetime, datetime]] = []
    for meeting in meetings:
        if not occupies_workday(meeting):
            continue
        start = max(as_utc(meeting.start), as_utc(window_start))
        end = min(as_utc(meeting.end), as_utc(window_end))
        if end > start:
            clipped.append((start, end))
    return _merge(clipped)


def _ceil_minute(value: datetime) -> datetime:
    if value.second == 0 and value.microsecond == 0:
        return value
    return value.replace(second=0, microsecond=0) + timedelta(minutes=1)


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    current_start, current_end = ordered[0]
    merged: list[tuple[datetime, datetime]] = []
    for start, end in ordered[1:]:
        if start <= current_end:
            if end > current_end:
                current_end = end
            continue
        merged.append((current_start, current_end))
        current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def _merged_minutes(intervals: list[tuple[datetime, datetime]]) -> int:
    return sum(_minutes_between(start, end) for start, end in _merge(intervals))


def _minutes_between(start: datetime, end: datetime) -> int:
    return int(round((end - start).total_seconds() / 60))
