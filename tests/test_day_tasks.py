"""Each day shows the tasks scheduled for that day."""

from __future__ import annotations

import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.services.alarms import TodoRecord
from app.ui.calendar_widget import CalendarWidget
from app.ui.meeting_widget import TaskWidget
from app.ui.theme import apply_theme
from zoneinfo import ZoneInfo


class DayTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._application = QApplication.instance() or QApplication([])
        apply_theme(cls._application)

    def test_week_strip_and_agenda_keep_each_days_tasks(self) -> None:
        tz = ZoneInfo("Asia/Tehran")
        friday = date(2026, 11, 20)
        widget = CalendarWidget(tz, "monday", "agenda")
        widget.resize(1100, 700)
        widget._anchor = friday
        widget.set_todos(
            [
                TodoRecord("fri-late", "File the report", "2026-11-20", "16:00", "normal"),
                TodoRecord("fri-high", "Call the vendor", "2026-11-20", "09:00", "high"),
                TodoRecord("fri-done", "Send notes", "2026-11-20", "11:00", "normal", completed=True),
                TodoRecord("sat", "Saturday note", "2026-11-21", "", "low"),
            ]
        )
        widget.show()
        self._application.processEvents()

        titles = [row.todo.title for row in widget.findChildren(TaskWidget)]
        self.assertEqual(titles.count("Call the vendor"), 1)
        self.assertEqual(titles.count("Saturday note"), 1)
        friday_rows = [
            row.todo.title
            for row in widget.findChildren(TaskWidget)
            if row.todo.scheduled_date == "2026-11-20"
        ]
        self.assertEqual(friday_rows, ["Call the vendor", "Send notes", "File the report"])
        headers = [
            label.text()
            for label in widget.findChildren(QLabel)
            if label.objectName() in {"dayHeader", "dayHeaderToday"}
        ]
        self.assertTrue(any(text.endswith("· 3 tasks") and "November 20" in text for text in headers))
        self.assertTrue(any(text.endswith("· 1 task") and "November 21" in text for text in headers))

        widget.set_view("daily")
        self.assertEqual(widget.findChildren(TaskWidget), [])
        chip_titles = [
            chip.text()
            for chip in widget.time_grid.findChildren(QLabel)
            if chip.parent() is not None and chip.parent().objectName() == "allDayChip"
        ]
        self.assertIn("Call the vendor", chip_titles)
        self.assertIn("File the report", chip_titles)
        self.assertNotIn("Saturday note", chip_titles)
        widget.close()
