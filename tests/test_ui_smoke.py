"""Launch the dashboard offscreen and exercise the demo calendar."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QSystemTrayIcon

from app.calendar.conflict_detector import ConflictPolicy, detect_conflicts
from app.config import AppPaths
from app.ui.main_window import MainWindow
from app.ui.meeting_details import MeetingDetailsDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import apply_theme


class DashboardSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._application = QApplication.instance() or QApplication([])
        apply_theme(cls._application)

    def test_demo_dashboard_navigation_conflicts_and_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow(demo=True, paths=AppPaths(Path(temporary)))
            window.show()
            deadline = time.time() + 8
            while time.time() < deadline:
                self._application.processEvents()
                if "Daily Standup" in window.calendar.subjects():
                    break
                time.sleep(0.02)
            else:
                self.fail("Demo meetings did not appear.")

            self.assertEqual(window.date_label.text().count(","), 2)
            self.assertIn("Project Planning", window.calendar.subjects())
            self.assertEqual(window.calendar.day_count(), 7)
            self.assertFalse(hasattr(window, "tasks"))
            self.assertEqual(window.splitter.count(), 2)
            self.assertEqual(window.messages.exchange_value.text(), "Demo mode")
            from app.ui.time_grid import EventBlock

            self.assertEqual(window.calendar.view, "weekly")
            blocks = window.calendar.findChildren(EventBlock)
            block_subjects = {block.meeting.subject for block in blocks}
            self.assertIn("Daily Standup", block_subjects)
            self.assertIn("Project Planning", block_subjects)
            window.calendar.set_view("agenda")
            self._application.processEvents()
            labels = [label.text() for label in window.calendar.findChildren(QLabel)]
            self.assertIn("Desk", labels)
            self.assertIn("John Smith", labels)
            self.assertIn("Organizer", labels)
            window.calendar.set_view("weekly")
            marks = [label.text() for label in window.calendar.now_next.findChildren(QLabel)]
            self.assertIn("Now", marks)
            self.assertIn("Next", marks)
            self.assertIn("Open", marks)
            self.assertTrue(window.calendar.now_next.open_text.text())
            self.assertTrue(window.calendar.now_next.now_subject.text())
            self.assertTrue(window.calendar.now_next.next_subject.text())

            anchor = window.calendar.anchor
            window.calendar.go_next()
            self.assertNotEqual(window.calendar.anchor, anchor)
            self.assertEqual(window.calendar.day_count(), 7)
            window.calendar.go_today()
            self.assertEqual(window.calendar.anchor, anchor)
            window.calendar.set_view("daily")
            self.assertEqual(window.calendar.view, "daily")
            self.assertEqual(window.calendar.day_count(), 1)
            self.assertIn("Daily Standup", window.calendar.subjects())
            window.calendar.go_previous()
            window.calendar.go_next()
            window.calendar.set_view("weekly")
            self.assertEqual(window.calendar.day_count(), 7)

            snapshot = window._snapshot
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            planning = next(item for item in snapshot.meetings if item.subject == "Project Planning")
            displayed = [item for item in snapshot.meetings if window._visible_meeting(item)]
            report = detect_conflicts(displayed, ConflictPolicy())
            self.assertTrue(report.has_conflict(planning.uid))
            dialog = MeetingDetailsDialog(planning, report, {item.uid: item for item in displayed}, window._tz)
            dialog.show()
            self._application.processEvents()
            conflict_labels = [
                label.text()
                for label in dialog.findChildren(type(window.date_label))
                if "Conflict Window" in label.text() or "30 minutes" in label.text()
            ]
            self.assertTrue(any("30 minutes" in text for text in conflict_labels))
            self.assertTrue(dialog.link_button.isHidden())
            dialog.close()

            customer = next(item for item in snapshot.meetings if item.subject == "Customer Meeting")
            customer_dialog = MeetingDetailsDialog(
                customer,
                report,
                {item.uid: item for item in displayed},
                window._tz,
            )
            self.assertFalse(customer_dialog.link_button.isHidden())
            customer_dialog.close()

            from app.calendar.agenda import agenda_at
            from app.calendar.demo_data import build_demo_meetings

            sample = build_demo_meetings(datetime(2026, 11, 19, tzinfo=window._tz).date(), window._tz)
            moment = datetime(2026, 11, 19, 14, 10, tzinfo=window._tz)
            current, upcoming = agenda_at(sample, moment)
            window.calendar.now_next.show_agenda(current, upcoming, moment, window._tz)
            self.assertEqual(window.calendar.now_next.now_subject.text(), "Customer Meeting")
            self.assertIn("until 15:00", window.calendar.now_next.now_when.text())
            self.assertFalse(window.calendar.now_next.now_join.isHidden())
            self.assertEqual(window.calendar.now_next.next_subject.text(), "Internal Discussion")
            self.assertIn("in 20 min", window.calendar.now_next.next_when.text())
            self.assertTrue(window.calendar.now_next.next_join.isHidden())

            settings = SettingsDialog(window.config, "", window)
            settings.show()
            self._application.processEvents()
            settings.close()

            window._on_auto_toggled(False)
            self.assertFalse(window.refresh_service._timer.isActive())
            window._on_interval_changed(10)
            self.assertEqual(window.config.refresh_interval_minutes, 10)
            window._on_auto_toggled(True)
            self.assertTrue(window.refresh_service._timer.isActive())
            self.assertEqual(window.refresh_service._timer.interval(), 10 * 60 * 1000)
            window._on_interval_changed(5)

            window.quit_application()
            self._application.processEvents()

    def test_connection_panel_slides_closed_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow(demo=True, paths=AppPaths(Path(temporary)))
            window.show()
            self._application.processEvents()
            self.assertFalse(window._connection_open)
            self.assertEqual(window._connection_stack.currentIndex(), 1)
            self.assertEqual(window.splitter.sizes()[1], 48)

            window._set_connection_open(True, animate=False, persist=False)
            self._application.processEvents()
            self.assertTrue(window._connection_open)
            self.assertEqual(window._connection_stack.currentIndex(), 0)
            self.assertGreaterEqual(window.splitter.sizes()[1], 280)

            window._toggle_connection()
            deadline = time.time() + 1
            while time.time() < deadline and window._connection_animating:
                self._application.processEvents()
                time.sleep(0.01)
            self._application.processEvents()
            self.assertFalse(window._connection_open)
            self.assertEqual(window._connection_stack.currentIndex(), 1)
            self.assertEqual(window.splitter.sizes()[1], 48)
            self.assertFalse(window.config.connection_open)
            window.quit_application()
            self._application.processEvents()

    def test_tasks_rail_opens_the_panel_and_saves_a_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow(demo=True, paths=AppPaths(Path(temporary)))
            window.show()
            self._application.processEvents()
            self.assertFalse(window._connection_open)

            window._rail_tasks.click()
            deadline = time.time() + 1
            while time.time() < deadline and window._connection_animating:
                self._application.processEvents()
                time.sleep(0.01)
            self._application.processEvents()

            self.assertTrue(window._connection_open)
            self.assertEqual(window._context_mode, "tasks")
            self.assertEqual(window._context_pages.currentWidget(), window.todo_board)
            window.todo_board.add_button.click()
            window.todo_board._title.setText("Prepare the notes")
            window.todo_board._save.click()
            self._application.processEvents()
            self.assertEqual([item.title for item in window.reminders.todos], ["Prepare the notes"])
            titles = [label.text() for label in window.todo_board.findChildren(type(window.date_label))]
            self.assertIn("Prepare the notes", titles)
            window.quit_application()
            self._application.processEvents()

    def test_exit_quits_while_the_tray_is_keeping_the_app_alive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow(demo=True, paths=AppPaths(Path(temporary)))
            window.show()
            self._application.processEvents()
            quits: list[bool] = []
            original_quit = self._application.quit

            def record_quit() -> None:
                quits.append(True)

            self._application.quit = record_quit
            try:
                with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
                    window.config.minimize_to_tray = True
                    window._sync_tray()
                    self.assertFalse(self._application.quitOnLastWindowClosed())
                    self.assertIsNotNone(window.tray)
                    window.close()
                    self._application.processEvents()
                    self.assertTrue(window.isHidden())
                    self.assertFalse(window._closing)
                    self.assertEqual(quits, [])

                    window.quit_application()
                    self._application.processEvents()
            finally:
                self._application.quit = original_quit
                self._application.setQuitOnLastWindowClosed(True)

            self.assertTrue(window._closing)
            self.assertFalse(window.isVisible())
            self.assertEqual(quits, [True])
            self.assertTrue(self._application.quitOnLastWindowClosed())


if __name__ == "__main__":
    unittest.main()
