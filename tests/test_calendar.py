"""Date navigation, demo data, HTML sanitizing, and Exchange field mapping."""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import ConflictPolicy, detect_conflicts
from app.calendar.date_utils import (
    format_long_date,
    intersects_day,
    period_label,
    shift_anchor,
    summary_text,
    visible_days,
    week_bounds,
)
from app.calendar.demo_data import build_demo_meetings
from app.calendar.workday import format_hours, free_blocks, open_time_summary, workday_load
from app.models import Meeting
from app.config import AppConfig
from app.exchange.authentication import format_username, tls_verify_setting
from app.exchange.calendar_service import extract_online_meeting_url, map_calendar_item
from app.html_text import sanitize_html


class CalendarDateTests(unittest.TestCase):
    def test_long_date_matches_outlook_today(self) -> None:
        self.assertEqual(format_long_date(date(2026, 11, 19)), "Thursday, November 19, 2026")

    def test_week_starts_monday_or_sunday(self) -> None:
        thursday = date(2026, 11, 19)
        self.assertEqual(week_bounds(thursday, "monday"), (date(2026, 11, 16), date(2026, 11, 22)))
        self.assertEqual(week_bounds(thursday, "sunday"), (date(2026, 11, 15), date(2026, 11, 21)))
        self.assertEqual(len(visible_days(thursday, "weekly", "monday")), 7)
        self.assertEqual(visible_days(thursday, "daily", "monday"), [thursday])

    def test_previous_next_and_today_navigation(self) -> None:
        thursday = date(2026, 11, 19)
        self.assertEqual(shift_anchor(thursday, "daily", -1), date(2026, 11, 18))
        self.assertEqual(shift_anchor(thursday, "daily", 1), date(2026, 11, 20))
        self.assertEqual(shift_anchor(thursday, "weekly", -1), date(2026, 11, 12))
        self.assertEqual(shift_anchor(thursday, "weekly", 1), date(2026, 11, 26))
        self.assertEqual(shift_anchor(thursday, "agenda", 1), date(2026, 11, 26))
        self.assertEqual(shift_anchor(date(2026, 1, 31), "monthly", 1), date(2026, 2, 28))
        self.assertEqual(shift_anchor(date(2026, 3, 31), "monthly", -1), date(2026, 2, 28))
        self.assertEqual(len(visible_days(thursday, "monthly", "monday")), 30)
        self.assertEqual(period_label(thursday, "daily", "monday", thursday), "Today")
        self.assertEqual(period_label(thursday, "weekly", "monday", thursday), "This Week")

    def test_summary_pluralization(self) -> None:
        self.assertEqual(summary_text("Today", 1, 0), "Today: 1 Meeting | No conflicts")
        self.assertEqual(
            summary_text("Today", 6, 2),
            "Today: 6 Meetings | 2 Conflicting Meetings",
        )

    def test_midnight_meeting_belongs_to_both_local_days(self) -> None:
        tz = ZoneInfo("Asia/Tehran")
        start = datetime(2026, 11, 19, 23, 30, tzinfo=tz)
        end = datetime(2026, 11, 20, 0, 30, tzinfo=tz)
        self.assertTrue(intersects_day(start, end, date(2026, 11, 19), tz))
        self.assertTrue(intersects_day(start, end, date(2026, 11, 20), tz))
        self.assertFalse(intersects_day(start, end, date(2026, 11, 18), tz))

    def test_daylight_saving_week_still_has_seven_dates(self) -> None:
        # 2026-03-08 is the US spring-forward Sunday. The week is still seven dates.
        anchor = date(2026, 3, 10)
        start, end = week_bounds(anchor, "sunday")
        self.assertEqual((end - start).days, 6)
        self.assertEqual(len(visible_days(anchor, "weekly", "sunday")), 7)

    def test_demo_mode_has_the_sample_conflicts(self) -> None:
        tz = ZoneInfo("UTC")
        today = date(2026, 11, 19)
        meetings = build_demo_meetings(today, tz)
        by_subject = {meeting.subject: meeting for meeting in meetings if meeting.start.astimezone(tz).date() == today}
        self.assertIn("Daily Standup", by_subject)
        self.assertIn("Project Planning", by_subject)
        self.assertIn("Customer Meeting", by_subject)
        self.assertIn("Internal Discussion", by_subject)
        report = detect_conflicts(meetings, ConflictPolicy())
        self.assertTrue(report.has_conflict(by_subject["Project Planning"].uid))
        self.assertTrue(report.has_conflict(by_subject["Daily Standup"].uid))
        self.assertTrue(report.has_conflict(by_subject["Internal Discussion"].uid))
        self.assertFalse(report.has_conflict(by_subject["Technical Review"].uid))
        self.assertFalse(report.has_conflict(by_subject["Focus Time"].uid))
        self.assertFalse(report.has_conflict(by_subject["Company Announcement"].uid))
        customer = by_subject["Customer Meeting"]
        self.assertEqual(customer.online_meeting_url, "https://teams.microsoft.com/l/meetup-join/demo-customer")


class HtmlAndMappingTests(unittest.TestCase):
    def test_sanitizer_removes_scripts_and_unsafe_links(self) -> None:
        raw = (
            "<p>Hello <b>team</b></p><script>alert(1)</script>"
            '<a href="javascript:alert(1)">bad</a>'
            '<a href="https://example.com/notes">notes</a>'
        )
        cleaned = sanitize_html(raw)
        self.assertIn("<b>team</b>", cleaned)
        self.assertNotIn("script", cleaned.lower())
        self.assertNotIn("javascript:", cleaned.lower())
        self.assertIn("https://example.com/notes", cleaned)

    def test_username_formatting(self) -> None:
        self.assertEqual(format_username("username", "DOMAIN"), r"DOMAIN\username")
        self.assertEqual(format_username(r"DOMAIN\username", "OTHER"), r"DOMAIN\username")
        self.assertEqual(format_username("user@company.com", "DOMAIN"), "user@company.com")

    def test_tls_verification_cannot_be_disabled(self) -> None:
        self.assertIs(tls_verify_setting(""), True)
        self.assertEqual(tls_verify_setting("/etc/ssl/certs/ca.pem"), "/etc/ssl/certs/ca.pem")
        self.assertIsNot(tls_verify_setting(""), False)

    def test_calendar_item_mapping_reads_exchange_fields(self) -> None:
        class Mailbox:
            def __init__(self, name, email):
                self.name = name
                self.email_address = email

        class Person:
            def __init__(self, name, email, response):
                self.mailbox = Mailbox(name, email)
                self.response_type = response

        class Body:
            body_type = "HTML"
            def __str__(self):
                return "<p>Review the <b>design</b>.</p><script>nope()</script>"

        class ItemId:
            id = "ews-id-1"

        class Item:
            subject = "Project Architecture Review"
            start = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
            end = datetime(2026, 11, 19, 11, 0, tzinfo=timezone.utc)
            organizer = Mailbox("John", "john@company.com")
            required_attendees = [Person("Alice", "alice@company.com", "Accept")]
            optional_attendees = [Person("Dana", "dana@company.com", "NoResponseReceived")]
            location = "Meeting Room 2 https://teams.microsoft.com/l/meetup-join/abc"
            body = Body()
            legacy_free_busy_status = "Busy"
            my_response_type = "Accept"
            is_all_day = False
            is_cancelled = False
            is_recurring = True
            type = "Occurrence"
            uid = "series-1"
            id = ItemId()

        mapped = map_calendar_item(Item(), "user@company.com", ZoneInfo("UTC"))
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped.uid, "ews-id-1")
        self.assertEqual(mapped.organizer_email, "john@company.com")
        self.assertEqual(mapped.required_attendees[0].response, "accepted")
        self.assertEqual(mapped.optional_attendees[0].response, "not_responded")
        self.assertTrue(mapped.is_recurring)
        self.assertEqual(mapped.online_meeting_url, "https://teams.microsoft.com/l/meetup-join/abc")
        self.assertNotIn("script", mapped.body_text.lower())
        self.assertEqual(extract_online_meeting_url(Item()), mapped.online_meeting_url)

    def test_join_link_comes_from_location_or_body(self) -> None:
        from app.calendar.links import find_meeting_url

        self.assertEqual(
            find_meeting_url("https://meet.google.com/abc-defg-hij", ""),
            "https://meet.google.com/abc-defg-hij",
        )
        self.assertEqual(
            find_meeting_url(
                "Meeting Room 2",
                "Agenda\nhttps://teams.microsoft.com/l/meetup-join/from-body",
            ),
            "https://teams.microsoft.com/l/meetup-join/from-body",
        )
        self.assertIsNone(find_meeting_url("Sara's Office", "See the project site https://example.com/notes"))

    def test_now_and_next_ignore_free_cancelled_and_all_day(self) -> None:
        from app.calendar.agenda import agenda_at

        tz = ZoneInfo("Asia/Tehran")
        meetings = build_demo_meetings(date(2026, 11, 19), tz)
        current, upcoming = agenda_at(meetings, datetime(2026, 11, 19, 9, 45, tzinfo=tz))
        self.assertEqual(current.subject, "Project Planning")
        self.assertEqual(upcoming.subject, "Technical Review")

        current, upcoming = agenda_at(meetings, datetime(2026, 11, 19, 14, 10, tzinfo=tz))
        self.assertEqual(current.subject, "Customer Meeting")
        self.assertEqual(upcoming.subject, "Internal Discussion")

        current, upcoming = agenda_at(meetings, datetime(2026, 11, 19, 23, 40, tzinfo=tz))
        self.assertEqual(current.subject, "Overnight Handoff")
        self.assertEqual(upcoming.subject, "Follow-the-Sun Sync")

    def test_exchange_datetime_can_be_stored(self) -> None:
        from exchangelib.ewsdatetime import EWSDateTime, EWSTimeZone

        from app.calendar.date_utils import stdlib_aware
        from app.models import to_utc_iso

        tehran = EWSTimeZone(key="Asia/Tehran")
        start = EWSDateTime(2026, 11, 19, 23, 30, tzinfo=tehran)
        self.assertEqual(to_utc_iso(start), "2026-11-19T20:00:00+00:00")
        self.assertIs(type(stdlib_aware(start)), datetime)


class SafetyTests(unittest.TestCase):
    def test_exchange_package_only_reads_the_calendar(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app" / "exchange"
        forbidden = (
            ".save(",
            ".delete(",
            ".move(",
            ".copy(",
            ".accept(",
            ".decline(",
            "account.inbox",
            "empty(",
        )
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} contains {token}")

    def test_dark_theme_can_be_selected_and_applied(self) -> None:
        self.assertEqual(AppConfig(theme="dark").normalized().theme, "dark")
        self.assertEqual(AppConfig(theme="blue").normalized().theme, "light")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from app.ui.theme import apply_theme

        app = QApplication.instance() or QApplication([])
        apply_theme(app, "dark")
        sheet = app.styleSheet()
        self.assertIn("#101010", sheet)
        self.assertNotIn("@page@", sheet)
        apply_theme(app, "light")


class WorkdayTests(unittest.TestCase):
    def test_workday_merges_overlaps_and_ignores_time_outside_tehran_hours(self) -> None:
        tehran = ZoneInfo("Asia/Tehran")
        day = date(2026, 11, 20)

        def at(hour: int, minute: int = 0, *, day_number: int = 20) -> datetime:
            return datetime(2026, 11, day_number, hour, minute, tzinfo=tehran)

        meetings = [
            Meeting("early", "Early", at(7), at(9)),
            Meeting("stand", "Standup", at(9), at(10)),
            Meeting("plan", "Planning", at(9, 30), at(10, 30)),
            Meeting("late", "Late", at(17), at(19)),
            Meeting("free", "Focus", at(12), at(13), busy_status="free"),
            Meeting("cancelled", "Cancelled", at(13), at(14), is_cancelled=True),
            Meeting("all-day", "Away", at(8), at(18), is_all_day=True),
            Meeting("declined", "Skip", at(15), at(16), response_status="declined"),
            Meeting("other-day", "Tomorrow", at(9, day_number=21), at(10, day_number=21)),
        ]
        load = workday_load(meetings, day)
        self.assertEqual(load.busy_minutes, 210)
        self.assertEqual(load.free_minutes, 390)
        self.assertEqual(format_hours(load.busy_minutes), "3h 30m")
        self.assertEqual(format_hours(load.free_minutes), "6h 30m")

    def test_utc_meeting_is_measured_on_the_tehran_clock(self) -> None:
        start = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)
        end = datetime(2026, 11, 20, 6, 30, tzinfo=timezone.utc)
        load = workday_load([Meeting("utc", "Call", start, end)], date(2026, 11, 20))
        self.assertEqual(load.busy_minutes, 60)
        self.assertEqual(load.free_minutes, 540)

    def test_empty_workday_is_ten_free_hours(self) -> None:
        load = workday_load([], date(2026, 11, 21))
        self.assertEqual(load.busy_minutes, 0)
        self.assertEqual(load.free_minutes, 600)

    def test_demo_friday_workday(self) -> None:
        tehran = ZoneInfo("Asia/Tehran")
        day = date(2026, 11, 20)
        load = workday_load(build_demo_meetings(day, tehran), day)
        self.assertEqual(load.busy_minutes, 270)
        self.assertEqual(load.free_minutes, 330)

    def test_open_blocks_skip_cancelled_free_declined_and_all_day(self) -> None:
        tehran = ZoneInfo("Asia/Tehran")
        day = date(2026, 11, 20)
        morning = datetime(2026, 11, 20, 7, 30, tzinfo=tehran)
        meetings = [
            Meeting("a", "Review", datetime(2026, 11, 20, 8, tzinfo=tehran), datetime(2026, 11, 20, 11, 30, tzinfo=tehran)),
            Meeting("b", "Design", datetime(2026, 11, 20, 13, tzinfo=tehran), datetime(2026, 11, 20, 16, 15, tzinfo=tehran)),
            Meeting("free", "Focus", datetime(2026, 11, 20, 11, 30, tzinfo=tehran), datetime(2026, 11, 20, 13, tzinfo=tehran), busy_status="free"),
            Meeting("cancelled", "Dropped", datetime(2026, 11, 20, 16, 15, tzinfo=tehran), datetime(2026, 11, 20, 18, tzinfo=tehran), is_cancelled=True),
            Meeting("away", "Away", datetime(2026, 11, 20, 8, tzinfo=tehran), datetime(2026, 11, 20, 18, tzinfo=tehran), is_all_day=True),
            Meeting("declined", "Skip", datetime(2026, 11, 20, 16, 15, tzinfo=tehran), datetime(2026, 11, 20, 17, tzinfo=tehran), response_status="declined"),
        ]
        blocks = free_blocks(meetings, day, now=morning)
        self.assertEqual([(block.start.strftime("%H:%M"), block.end.strftime("%H:%M")) for block in blocks], [("11:30", "13:00"), ("16:15", "18:00")])
        today_text, later_text = open_time_summary(meetings, morning, "monday")
        self.assertEqual(today_text, "11:30–13:00 · 16:15–18:00")
        self.assertEqual(later_text, "")

    def test_passed_time_is_removed_and_the_next_hour_is_later_this_week(self) -> None:
        tehran = ZoneInfo("Asia/Tehran")
        friday = date(2026, 11, 20)
        now = datetime(2026, 11, 20, 17, 30, tzinfo=tehran)
        meetings = [
            Meeting("packed", "Packed", datetime(2026, 11, 20, 8, tzinfo=tehran), datetime(2026, 11, 20, 17, 20, tzinfo=tehran)),
            Meeting("monday", "Monday", datetime(2026, 11, 23, 9, 30, tzinfo=tehran), datetime(2026, 11, 23, 18, tzinfo=tehran)),
        ]
        blocks = free_blocks(meetings, friday, now=now)
        self.assertEqual([(block.start.strftime("%H:%M"), block.end.strftime("%H:%M")) for block in blocks], [("17:30", "18:00")])
        today_text, later_text = open_time_summary(meetings, now, "monday")
        self.assertEqual(today_text, "17:30–18:00")
        self.assertEqual(later_text, "60m Tomorrow 08:00–18:00")
        self.assertEqual(free_blocks(meetings, friday, now=datetime(2026, 11, 20, 18, tzinfo=tehran)), [])


if __name__ == "__main__":
    unittest.main()
