"""Conflict detection cases required by the calendar dashboard."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import (
    ConflictPolicy,
    common_overlap,
    detect_conflicts,
    format_conflict_popup,
)
from app.models import Meeting


UTC = timezone.utc


def meeting(uid: str, start: datetime, end: datetime, **kwargs) -> Meeting:
    if start.tzinfo is None or end.tzinfo is None:
        raise AssertionError("Test meetings must be timezone-aware.")
    return Meeting(uid=uid, subject=kwargs.pop("subject", uid), start=start, end=end, **kwargs)


def at(hour: int, minute: int = 0, *, day: int = 19, month: int = 11, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class ConflictDetectionTests(unittest.TestCase):
    def test_partial_overlap(self) -> None:
        standup = meeting("a", at(9, 0), at(10, 0), subject="Daily Standup")
        planning = meeting("b", at(9, 30), at(10, 30), subject="Project Planning")
        report = detect_conflicts([standup, planning])
        self.assertEqual(len(report.overlaps), 1)
        self.assertEqual(report.overlaps[0].minutes, 30)
        self.assertEqual(report.overlaps[0].start, at(9, 30))
        self.assertEqual(report.overlaps[0].end, at(10, 0))
        self.assertTrue(report.has_conflict("a"))
        self.assertTrue(report.has_conflict("b"))
        text = format_conflict_popup(planning, report, {"a": standup, "b": planning}, ZoneInfo("UTC"))
        self.assertIn("Meeting Conflict Detected", text)
        self.assertIn("Daily Standup", text)
        self.assertIn("Project Planning", text)
        self.assertIn("Conflict Window:", text)
        self.assertIn("09:30 - 10:00", text)
        self.assertIn("Total Overlap:", text)
        self.assertIn("30 minutes", text)

    def test_complete_overlap(self) -> None:
        outer = meeting("outer", at(9, 0), at(12, 0))
        inner = meeting("inner", at(10, 0), at(11, 0))
        report = detect_conflicts([inner, outer])
        self.assertEqual(len(report.overlaps), 1)
        self.assertEqual(report.overlaps[0].start, at(10, 0))
        self.assertEqual(report.overlaps[0].end, at(11, 0))
        self.assertEqual(report.overlaps[0].minutes, 60)

    def test_identical_meeting_times(self) -> None:
        first = meeting("one", at(9, 0), at(10, 0))
        second = meeting("two", at(9, 0), at(10, 0))
        report = detect_conflicts([first, second])
        self.assertEqual(len(report.overlaps), 1)
        self.assertEqual(report.overlaps[0].minutes, 60)
        self.assertEqual(report.conflicting_ids(), {"one", "two"})

    def test_back_to_back_meetings_are_not_conflicts(self) -> None:
        first = meeting("one", at(9, 0), at(10, 0))
        second = meeting("two", at(10, 0), at(11, 0))
        report = detect_conflicts([first, second])
        self.assertEqual(report.overlaps, [])

    def test_no_overlap(self) -> None:
        first = meeting("one", at(9, 0), at(10, 0))
        second = meeting("two", at(10, 30), at(11, 30))
        report = detect_conflicts([first, second])
        self.assertFalse(report.has_conflict("one"))
        self.assertEqual(report.overlaps, [])

    def test_three_simultaneous_meetings(self) -> None:
        first = meeting("a", at(9, 0), at(11, 0), subject="Architecture")
        second = meeting("b", at(9, 30), at(10, 30), subject="Planning")
        third = meeting("c", at(10, 0), at(12, 0), subject="Review")
        report = detect_conflicts([first, second, third])
        self.assertEqual(len(report.overlaps), 3)
        self.assertEqual(report.cluster_containing("a"), ["a", "b", "c"])
        shared = common_overlap([first, second, third])
        self.assertIsNotNone(shared)
        assert shared is not None
        self.assertEqual(shared, (at(10, 0), at(10, 30)))
        text = format_conflict_popup(
            second,
            report,
            {"a": first, "b": second, "c": third},
            ZoneInfo("UTC"),
        )
        self.assertIn("Architecture", text)
        self.assertIn("Planning", text)
        self.assertIn("Review", text)
        self.assertIn("Common overlap:", text)
        self.assertIn("10:00 - 10:30", text)

    def test_meetings_crossing_midnight(self) -> None:
        tz = ZoneInfo("Asia/Tehran")
        late = meeting(
            "late",
            datetime(2026, 11, 19, 23, 0, tzinfo=tz),
            datetime(2026, 11, 20, 1, 0, tzinfo=tz),
            subject="Overnight Handoff",
        )
        early = meeting(
            "early",
            datetime(2026, 11, 20, 0, 30, tzinfo=tz),
            datetime(2026, 11, 20, 2, 0, tzinfo=tz),
            subject="Follow-the-Sun Sync",
        )
        report = detect_conflicts([late, early])
        self.assertEqual(report.overlaps[0].minutes, 30)
        boundary = meeting(
            "next",
            datetime(2026, 11, 20, 1, 0, tzinfo=tz),
            datetime(2026, 11, 20, 2, 0, tzinfo=tz),
        )
        self.assertEqual(detect_conflicts([late, boundary]).overlaps, [])

    def test_recurring_occurrences_are_compared_individually(self) -> None:
        tz = ZoneInfo("UTC")
        occurrences = []
        for offset in range(5):
            day = datetime(2026, 11, 16, 9, 0, tzinfo=tz) + timedelta(days=offset)
            occurrences.append(
                meeting(
                    f"standup-{offset}",
                    day,
                    day + timedelta(minutes=30),
                    subject="Daily Standup",
                    is_recurring=True,
                    series_id="series-standup",
                )
            )
        conflict_day = datetime(2026, 11, 18, 9, 15, tzinfo=tz)
        extra = meeting("extra", conflict_day, conflict_day + timedelta(minutes=30), subject="Vendor Review")
        report = detect_conflicts([*occurrences, extra])
        self.assertEqual(len(report.overlaps), 1)
        self.assertTrue(report.has_conflict("standup-2"))
        self.assertTrue(report.has_conflict("extra"))
        self.assertFalse(report.has_conflict("standup-0"))
        self.assertFalse(report.has_conflict("standup-4"))

    def test_all_day_events_follow_policy(self) -> None:
        tz = ZoneInfo("UTC")
        all_day = meeting(
            "holiday",
            datetime(2026, 11, 19, 0, 0, tzinfo=tz),
            datetime(2026, 11, 20, 0, 0, tzinfo=tz),
            subject="Company Announcement",
            is_all_day=True,
            busy_status="busy",
        )
        timed = meeting("timed", at(10, 0), at(11, 0))
        self.assertEqual(detect_conflicts([all_day, timed]).overlaps, [])
        included = detect_conflicts([all_day, timed], ConflictPolicy(include_all_day=True))
        self.assertEqual(len(included.overlaps), 1)
        free_all_day = meeting(
            "free-day",
            all_day.start,
            all_day.end,
            is_all_day=True,
            busy_status="free",
        )
        self.assertEqual(
            detect_conflicts([free_all_day, timed], ConflictPolicy(include_all_day=True)).overlaps,
            [],
        )

    def test_timezone_and_daylight_saving_transitions(self) -> None:
        ny = ZoneInfo("America/New_York")
        spring_a = meeting(
            "spring-a",
            datetime(2026, 3, 8, 1, 0, tzinfo=ny),
            datetime(2026, 3, 8, 4, 0, tzinfo=ny),
        )
        spring_b = meeting(
            "spring-b",
            datetime(2026, 3, 8, 3, 30, tzinfo=ny),
            datetime(2026, 3, 8, 5, 0, tzinfo=ny),
        )
        spring = detect_conflicts([spring_a, spring_b])
        self.assertEqual(spring.overlaps[0].minutes, 30)
        self.assertEqual(spring.overlaps[0].start, datetime(2026, 3, 8, 3, 30, tzinfo=ny))

        # On the fall-back morning, 01:45 EDT is 05:45 UTC and the second 01:15 EST is
        # 06:15 UTC. The clock faces look like they overlap, and datetime ordering can
        # agree with the clock face. Absolute UTC must not report a conflict.
        fall_a = meeting(
            "fall-a",
            datetime(2026, 11, 1, 0, 30, tzinfo=ny),
            datetime(2026, 11, 1, 1, 45, fold=0, tzinfo=ny),
        )
        fall_b = meeting(
            "fall-b",
            datetime(2026, 11, 1, 1, 15, fold=1, tzinfo=ny),
            datetime(2026, 11, 1, 3, 0, tzinfo=ny),
        )
        self.assertLess(fall_a.end.timestamp(), fall_b.start.timestamp())
        self.assertEqual(detect_conflicts([fall_a, fall_b]).overlaps, [])

        spanning = meeting(
            "span",
            datetime(2026, 11, 1, 0, 30, tzinfo=ny),
            datetime(2026, 11, 1, 2, 30, tzinfo=ny),
        )
        repeated = meeting(
            "repeated",
            datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=ny),
            datetime(2026, 11, 1, 3, 0, tzinfo=ny),
        )
        folded = detect_conflicts([spanning, repeated])
        self.assertEqual(len(folded.overlaps), 1)
        self.assertGreater(folded.overlaps[0].minutes, 0)

    def test_cancelled_free_declined_and_tentative_policies(self) -> None:
        busy = meeting("busy", at(9, 0), at(10, 0))
        cancelled = meeting("cancelled", at(9, 15), at(9, 45), is_cancelled=True)
        free = meeting("free", at(9, 15), at(9, 45), busy_status="free")
        declined = meeting("declined", at(9, 15), at(9, 45), response_status="declined")
        tentative = meeting("tentative", at(9, 15), at(9, 45), busy_status="tentative")
        self.assertEqual(detect_conflicts([busy, cancelled, free, declined]).overlaps, [])
        self.assertEqual(detect_conflicts([busy, tentative], ConflictPolicy(include_tentative=False)).overlaps, [])
        included = detect_conflicts([busy, tentative], ConflictPolicy(include_tentative=True))
        self.assertEqual(len(included.overlaps), 1)

    def test_duplicate_pair_is_reported_once(self) -> None:
        first = meeting("a", at(9, 0), at(10, 0))
        second = meeting("b", at(9, 30), at(10, 30))
        report = detect_conflicts([first, second, second])
        self.assertEqual(len(report.overlaps), 1)


if __name__ == "__main__":
    unittest.main()
