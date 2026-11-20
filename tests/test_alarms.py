"""Meeting bells, task reminders, snooze, and restart persistence."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.config import AppConfig
from app.models import Meeting
from app.services.alarm_sound import play_alarm, render_wav
from app.services.alarms import (
    DueAlarm,
    TodoRecord,
    carry_forward,
    due_meeting_alarms,
    due_snoozes,
    due_todo_alarms,
    make_snooze,
    meeting_key,
)
from app.storage.reminders import ReminderStore

UTC = timezone.utc


def _meeting(uid: str, start: datetime, **kwargs) -> Meeting:
    return Meeting(uid=uid, subject=kwargs.pop("subject", uid), start=start, end=start + timedelta(minutes=30), **kwargs)


class AlarmScheduleTests(unittest.TestCase):
    def test_meeting_reminder_ten_minutes_before_and_at_start(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        meeting = _meeting("arch", start, subject="Architecture Review")
        early = due_meeting_alarms([meeting], start - timedelta(minutes=10), [10, 0], set())
        self.assertEqual([item.offset_minutes for item in early], [10])
        self.assertEqual(early[0].key, meeting_key(meeting, 10))
        at_start = due_meeting_alarms([meeting], start, [10, 0], {early[0].key})
        self.assertEqual([item.offset_minutes for item in at_start], [0])
        self.assertEqual(due_meeting_alarms([meeting], start - timedelta(minutes=11), [10, 0], set()), [])

    def test_todo_reminder_at_the_scheduled_minute(self) -> None:
        tz = UTC
        trigger = datetime(2026, 11, 20, 14, 0, tzinfo=tz)
        todo = TodoRecord("doc", "Complete API Documentation", "2026-11-20", "14:00", "high")
        self.assertEqual(due_todo_alarms([todo], trigger - timedelta(minutes=1), tz, set()), [])
        due = due_todo_alarms([todo], trigger, tz, set())
        self.assertEqual(due[0].title, "Complete API Documentation")
        self.assertEqual(due[0].priority, "high")

    def test_snoozed_meeting_and_todo_ring_again_once(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        meeting = _meeting("arch", start)
        original = due_meeting_alarms([meeting], start - timedelta(minutes=10), [10], set())[0]
        snooze = make_snooze(original, 5, start - timedelta(minutes=10))
        self.assertEqual(due_snoozes([snooze], start - timedelta(minutes=10), set()), [])
        again = due_snoozes([snooze], start - timedelta(minutes=5), set())
        self.assertEqual(again[0].source_id, "arch")
        self.assertTrue(again[0].snoozed)
        self.assertEqual(due_snoozes([snooze], start - timedelta(minutes=5), {snooze.key}), [])

        todo = DueAlarm(
            key="todo|doc|2026-11-20|14:00",
            kind="todo",
            source_id="doc",
            title="Complete API Documentation",
            event_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
            trigger_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
            offset_minutes=0,
            priority="high",
        )
        todo_snooze = make_snooze(todo, 10, todo.event_at)
        self.assertEqual(due_snoozes([todo_snooze], todo.event_at + timedelta(minutes=10), set())[0].kind, "todo")

    def test_reschedule_replaces_the_reminder_and_drops_the_snooze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ReminderStore(Path(temporary))
            todo = store.add_todo("Write notes", "2026-11-20", "14:00", "normal")
            alarm = DueAlarm(
                key="todo|" + todo.uid,
                kind="todo",
                source_id=todo.uid,
                title=todo.title,
                event_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
                trigger_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
                offset_minutes=0,
            )
            store.add_snooze(make_snooze(alarm, 5, alarm.event_at))
            store.update_todo(todo.uid, "Write notes", "2026-11-21", "15:00", "high")
            self.assertEqual(store.snoozes, [])
            self.assertEqual(store.todos[0].reminder_time, "15:00")
            quiet = TodoRecord("plain", "No bell", "2026-11-20", "")
            self.assertEqual(due_todo_alarms([quiet], datetime(2026, 11, 20, 9, 0, tzinfo=UTC), UTC, set()), [])

    def test_completed_task_cancels_its_reminder_and_snooze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ReminderStore(Path(temporary))
            todo = store.add_todo("Write notes", "2026-11-20", "14:00", "normal")
            alarm = DueAlarm(
                key="todo|" + todo.uid,
                kind="todo",
                source_id=todo.uid,
                title=todo.title,
                event_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
                trigger_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
                offset_minutes=0,
            )
            store.add_snooze(make_snooze(alarm, 5, alarm.event_at))
            store.complete(todo.uid)
            self.assertTrue(store.todos[0].completed)
            self.assertEqual(store.snoozes, [])
            self.assertEqual(
                due_todo_alarms(store.todos, datetime(2026, 11, 20, 14, 0, tzinfo=UTC), UTC, set()),
                [],
            )

    def test_carried_forward_task_uses_the_new_date(self) -> None:
        todo = TodoRecord("doc", "Finish report", "2026-11-19", "14:00", "normal")
        self.assertTrue(carry_forward([todo], date(2026, 11, 20), True))
        self.assertEqual(todo.scheduled_date, "2026-11-20")
        missed = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
        self.assertEqual(due_todo_alarms([todo], missed, UTC, set()), [])
        today = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
        self.assertEqual(due_todo_alarms([todo], today, UTC, set())[0].key, "todo|doc|2026-11-20|14:00")
        self.assertFalse(carry_forward([todo], date(2026, 11, 21), False))

    def test_cancelled_meeting_does_not_ring(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        meeting = _meeting("gone", start, is_cancelled=True)
        self.assertEqual(due_meeting_alarms([meeting], start - timedelta(minutes=10), [10, 0], set()), [])

    def test_simultaneous_meetings_are_both_listed_for_one_bell(self) -> None:
        start = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
        first = _meeting("a", start, subject="Standup")
        second = _meeting("b", start, subject="Planning")
        due = due_meeting_alarms([first, second], start - timedelta(minutes=10), [10], set())
        self.assertEqual({item.source_id for item in due}, {"a", "b"})

    def test_conflict_warning_names_the_other_meeting(self) -> None:
        start = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
        planning = _meeting("plan", start, subject="Project Planning")
        review = Meeting(
            "arch",
            "Architecture Review",
            start + timedelta(minutes=15),
            start + timedelta(minutes=45),
        )
        due = due_meeting_alarms([planning, review], start - timedelta(minutes=10), [10], set())
        warned = next(item for item in due if item.source_id == "plan")
        self.assertEqual(warned.conflict_name, "Architecture Review")
        self.assertGreater(warned.conflict_minutes, 0)

    def test_resume_within_three_minutes_still_rings_and_an_old_miss_does_not(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        meeting = _meeting("arch", start)
        self.assertTrue(due_meeting_alarms([meeting], start - timedelta(minutes=8), [10], set()))
        self.assertEqual(due_meeting_alarms([meeting], start - timedelta(minutes=6), [10], set()), [])

    def test_fired_keys_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ReminderStore(Path(temporary))
            store.mark_fired(["meeting|arch|2026-11-20T10:00:00+00:00|10"])
            restored = ReminderStore(Path(temporary))
            start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
            meeting = _meeting("arch", start)
            self.assertEqual(
                due_meeting_alarms([meeting], start - timedelta(minutes=10), [10], restored.fired),
                [],
            )

    def test_cached_calendar_is_marked_on_the_alarm(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        due = due_meeting_alarms([_meeting("arch", start)], start, [0], set(), cached=True)
        self.assertTrue(due[0].cached)

    def test_several_reminders_in_the_same_minute_stay_distinct(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        meeting = _meeting("arch", start)
        due = due_meeting_alarms([meeting], start, [0, 10], set())
        self.assertEqual(sorted(item.offset_minutes for item in due), [0])
        both = due_meeting_alarms(
            [meeting, _meeting("other", start)],
            start - timedelta(minutes=10),
            [10],
            set(),
        )
        self.assertEqual(len(both), 2)
        self.assertEqual(len({item.key for item in both}), 2)

    def test_exchange_reminder_can_replace_or_silence_the_default(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        custom = _meeting("arch", start, reminder_minutes=15)
        self.assertEqual(
            [item.offset_minutes for item in due_meeting_alarms([custom], start - timedelta(minutes=15), [10, 0], set(), respect_exchange=True)],
            [15],
        )
        silent = _meeting("quiet", start, reminder_minutes=-1)
        self.assertEqual(
            due_meeting_alarms([silent], start - timedelta(minutes=10), [10], set(), respect_exchange=True),
            [],
        )

    def test_audio_failure_does_not_raise(self) -> None:
        self.assertTrue(render_wav("classic").startswith(b"RIFF"))
        self.assertFalse(play_alarm(Path("/tmp"), "classic", 0, 1))
        self.assertFalse(play_alarm(Path("/tmp"), "classic", 80, 1, player=""))

    def test_join_reminder_uses_the_selected_lead_and_can_be_off(self) -> None:
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        linked = _meeting("arch", start, online_meeting_url="https://teams.microsoft.com/l/meetup-join/example")
        room = _meeting("room", start, location="Room 2")
        moment = start - timedelta(minutes=2)
        due = due_meeting_alarms([linked, room], moment, [10, 0], set(), join_minutes=2)
        self.assertEqual([item.source_id for item in due], ["arch"])
        self.assertEqual(due[0].offset_minutes, 2)
        self.assertEqual(due[0].url, "https://teams.microsoft.com/l/meetup-join/example")
        self.assertEqual(due_meeting_alarms([linked], moment, [10, 0], set(), join_minutes=0), [])
        same_minute = due_meeting_alarms([linked], start - timedelta(minutes=10), [10], set(), join_minutes=10)
        self.assertEqual(len(same_minute), 1)

    def test_legacy_config_keeps_its_single_reminder(self) -> None:
        legacy = AppConfig.from_dict({"join_reminder_minutes": 5})
        self.assertEqual(legacy.meeting_reminder_offsets, [5])
        fresh = AppConfig().normalized()
        self.assertEqual(fresh.meeting_reminder_offsets, [10, 0])

    def test_overdue_task_rings_once_on_the_same_day_only(self) -> None:
        todo = TodoRecord("doc", "File report", "2026-11-20", "09:00")
        later = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
        self.assertTrue(due_todo_alarms([todo], later, UTC, set(), overdue=True))
        self.assertEqual(due_todo_alarms([todo], later, UTC, set(), overdue=False), [])
        self.assertEqual(due_todo_alarms([todo], datetime(2026, 11, 21, 9, 0, tzinfo=UTC), UTC, set()), [])


class AlarmWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        from app.ui.theme import apply_theme

        cls._application = QApplication.instance() or QApplication([])
        apply_theme(cls._application)

    def test_popup_offers_join_snooze_and_task_actions(self) -> None:
        from PySide6.QtWidgets import QPushButton

        from app.ui.alarm_popup import AlarmPopup

        now = datetime(2026, 11, 20, 9, 50, tzinfo=UTC)
        meeting = DueAlarm(
            key="meeting|arch",
            kind="meeting",
            source_id="arch",
            title="Architecture Review",
            event_at=datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
            trigger_at=now,
            offset_minutes=10,
            url="https://teams.microsoft.com/l/meetup-join/example",
            conflict_name="Project Planning",
            conflict_minutes=30,
        )
        popup = AlarmPopup(meeting, UTC, now, True)
        labels = {button.text() for button in popup.findChildren(QPushButton)}
        self.assertTrue({"Join Meeting", "View Conflict", "Snooze", "Dismiss"} <= labels)
        popup.close()

        task = DueAlarm(
            key="todo|doc",
            kind="todo",
            source_id="doc",
            title="Complete API Documentation",
            event_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
            trigger_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
            offset_minutes=0,
            priority="high",
        )
        task_popup = AlarmPopup(task, UTC, task.event_at, True)
        task_labels = {button.text() for button in task_popup.findChildren(QPushButton)}
        self.assertTrue({"Mark as Done", "Open Task", "Snooze", "Dismiss"} <= task_labels)
        task_popup.close()

    def test_scheduler_runs_while_the_window_exists(self) -> None:
        from app.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as temporary:
            from app.config import AppPaths

            window = MainWindow(demo=True, paths=AppPaths(Path(temporary)))
            self.assertEqual(window._alarm_timer.interval(), 30_000)
            self.assertTrue(window._alarm_timer.isActive())
            self.assertFalse(hasattr(window, "tasks"))
            window._check_alarms()
            window.quit_application()
            self._application.processEvents()
