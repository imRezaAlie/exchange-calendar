"""Week grid places meetings on the clock, including overlaps and daylight-saving days."""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from zoneinfo import ZoneInfo

from app.calendar.conflict_detector import ConflictReport
from app.models import Meeting
from app.ui.theme import apply_theme
from app.ui.time_grid import HOUR_HEIGHT, EventBlock, TimeGrid, minute_span


def _meeting(uid: str, start: datetime, end: datetime, subject: str, all_day: bool = False) -> Meeting:
    return Meeting(uid=uid, subject=subject, start=start, end=end, is_all_day=all_day)


class TimeGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._application = QApplication.instance() or QApplication([])
        apply_theme(cls._application, "dark")

    def test_wall_clock_span_survives_a_short_daylight_saving_day(self) -> None:
        tz = ZoneInfo("America/New_York")
        # 2026-03-08 is the US spring-forward. 10:00 still means 10:00 local.
        day = date(2026, 3, 8)
        meeting = _meeting(
            "dst",
            datetime(2026, 3, 8, 10, 0, tzinfo=tz),
            datetime(2026, 3, 8, 11, 30, tzinfo=tz),
            "Planning",
        )
        self.assertEqual(minute_span(meeting, day, tz), (10 * 60, 11 * 60 + 30))
        self.assertIsNone(minute_span(meeting, date(2026, 3, 7), tz))

    def test_overlap_is_side_by_side_and_height_follows_duration(self) -> None:
        tz = ZoneInfo("UTC")
        day = date(2026, 11, 20)
        short = _meeting(
            "short",
            datetime(2026, 11, 20, 10, 0, tzinfo=tz),
            datetime(2026, 11, 20, 11, 0, tzinfo=tz),
            "Standup",
        )
        long = _meeting(
            "long",
            datetime(2026, 11, 20, 10, 30, tzinfo=tz),
            datetime(2026, 11, 20, 12, 0, tzinfo=tz),
            "Review",
        )
        later = _meeting(
            "later",
            datetime(2026, 11, 20, 14, 0, tzinfo=tz),
            datetime(2026, 11, 20, 15, 0, tzinfo=tz),
            "Customer",
        )
        grid = TimeGrid()
        grid.resize(900, 700)
        grid.show_days(
            [day],
            [short, long, later],
            [],
            ConflictReport(),
            tz,
            datetime(2026, 11, 20, 9, 0, tzinfo=tz),
            True,
            "",
            True,
        )
        grid.show()
        self._application.processEvents()
        blocks = {block.meeting.uid: block for block in grid.findChildren(EventBlock)}
        self.assertEqual(set(blocks), {"short", "long", "later"})
        self.assertLess(blocks["short"].y(), blocks["later"].y())
        self.assertGreater(blocks["long"].height(), blocks["short"].height())
        self.assertNotEqual(blocks["short"].x(), blocks["long"].x())
        self.assertAlmostEqual(blocks["short"].y(), 10 * HOUR_HEIGHT, delta=2)
        self.assertAlmostEqual(blocks["later"].y(), 14 * HOUR_HEIGHT, delta=2)
        grid.close()


if __name__ == "__main__":
    unittest.main()
