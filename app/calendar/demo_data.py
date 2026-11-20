"""Sample meetings used by demo mode and by the conflict tests' realistic path."""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.calendar.date_utils import start_of_day
from app.models import Attendee, Meeting

DEMO_MAILBOX = "demo@local"

_REQUIRED = (
    Attendee("Alice", "alice@company.com", True, "accepted"),
    Attendee("Bob", "bob@company.com", True, "accepted"),
    Attendee("Charlie", "charlie@company.com", True, "tentative"),
)
_OPTIONAL = (Attendee("Dana", "dana@company.com", False, "not_responded"),)


def _description(subject: str, extra: str = "") -> tuple[str, str]:
    body = f"<p>{html.escape(subject)}</p><p>Agenda and conference details.</p>"
    if extra:
        body += extra
    text = subject + "\nAgenda and conference details."
    return body, text


def build_demo_meetings(today: date, tz: ZoneInfo) -> list[Meeting]:
    """Build a realistic week with the overlapping meetings used in the brief."""
    meetings: list[Meeting] = []

    def add(
        day: date,
        start_hour: int,
        start_minute: int,
        end_hour: int,
        end_minute: int,
        subject: str,
        *,
        busy_status: str = "busy",
        response_status: str = "accepted",
        is_all_day: bool = False,
        is_cancelled: bool = False,
        is_recurring: bool = False,
        series_id: str | None = None,
        location: str = "",
        online_meeting_url: str | None = None,
        organizer_name: str = "John Smith",
        organizer_email: str = "john@company.com",
        body_extra: str = "",
    ) -> None:
        if is_all_day:
            start = start_of_day(day, tz)
            end = start_of_day(day + timedelta(days=1), tz)
        else:
            start = datetime(day.year, day.month, day.day, start_hour, start_minute, tzinfo=tz)
            end_day = day
            if (end_hour, end_minute) <= (start_hour, start_minute):
                end_day = day + timedelta(days=1)
            end = datetime(end_day.year, end_day.month, end_day.day, end_hour, end_minute, tzinfo=tz)
        body_html, body_text = _description(subject, body_extra)
        slug = "".join(character.lower() if character.isalnum() else "-" for character in subject)
        meetings.append(
            Meeting(
                uid=f"demo-{slug}-{day.isoformat()}-{start_hour:02d}{start_minute:02d}",
                subject=subject,
                start=start,
                end=end,
                organizer_name=organizer_name,
                organizer_email=organizer_email,
                required_attendees=list(_REQUIRED),
                optional_attendees=list(_OPTIONAL),
                location=location,
                body_html=body_html,
                body_text=body_text,
                busy_status=busy_status,
                response_status=response_status,
                online_meeting_url=online_meeting_url,
                is_all_day=is_all_day,
                is_cancelled=is_cancelled,
                is_recurring=is_recurring,
                series_id=series_id,
                mailbox=DEMO_MAILBOX,
            )
        )

    add(today, 0, 0, 0, 0, "Company Announcement", busy_status="free", is_all_day=True, location="")
    add(
        today,
        8,
        0,
        8,
        30,
        "Mailbox Review",
        location="Desk",
        is_recurring=True,
        series_id="series-mailbox-review",
    )
    add(
        today,
        9,
        0,
        10,
        0,
        "Daily Standup",
        location="Microsoft Teams",
        is_recurring=True,
        series_id="series-standup",
        online_meeting_url="https://teams.microsoft.com/l/meetup-join/demo-standup",
    )
    add(today, 9, 30, 10, 30, "Project Planning", location="Meeting Room 2")
    add(today, 11, 0, 12, 0, "Technical Review", location="Meeting Room 4")
    add(
        today,
        11,
        0,
        12,
        0,
        "Vendor Call",
        is_cancelled=True,
        location="Phone",
        response_status="not_responded",
    )
    add(
        today,
        14,
        0,
        15,
        0,
        "Customer Meeting",
        location="Microsoft Teams",
        online_meeting_url="https://teams.microsoft.com/l/meetup-join/demo-customer",
        body_extra=(
            "<ul><li>Status</li><li>Timeline</li><li>Risks</li></ul>"
            '<p><a href="https://teams.microsoft.com/l/meetup-join/demo-customer">Join Teams</a></p>'
        ),
    )
    add(today, 14, 0, 15, 0, "Focus Time", busy_status="free", location="Desk")
    add(today, 14, 30, 15, 30, "Internal Discussion", location="Meeting Room 1")
    add(today, 19, 0, 19, 45, "Optional Workshop", busy_status="tentative", response_status="tentative")
    add(today, 19, 30, 20, 15, "Tentative Office Hours", busy_status="tentative", response_status="tentative")

    tomorrow = today + timedelta(days=1)
    add(today, 23, 30, 0, 30, "Overnight Handoff", location="Bridge line")
    add(tomorrow, 0, 0, 1, 0, "Follow-the-Sun Sync", location="Bridge line")
    add(tomorrow, 10, 0, 11, 0, "Architecture Meeting", location="Meeting Room 3")
    add(tomorrow, 10, 30, 11, 30, "Staffing Review", location="Meeting Room 3")

    for offset in range(-7, 15):
        if offset in {0, 1}:
            continue
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        add(
            day,
            9,
            0,
            9,
            30,
            "Daily Standup",
            location="Microsoft Teams",
            is_recurring=True,
            series_id="series-standup",
            online_meeting_url="https://teams.microsoft.com/l/meetup-join/demo-standup",
        )
        if offset % 2 == 0:
            add(day, 11, 0, 12, 0, "Project Review", location="Meeting Room 5")

    yesterday = today - timedelta(days=1)
    if yesterday.weekday() < 5:
        add(yesterday, 15, 0, 16, 0, "Design Review", location="Meeting Room 2")

    return meetings
