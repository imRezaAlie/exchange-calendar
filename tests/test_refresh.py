"""Cache, configuration, refresh gating, and offline fallback."""

from __future__ import annotations

import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import AppConfig, AppPaths, load_config, set_launch_at_login
from app.exchange.errors import ExchangeError
from app.logging_config import redact
from app.models import Meeting
from app.services.sync import NOT_CONFIGURED, SingleFlight, SyncRequest, perform_sync
from app.storage.cache import CalendarCache


def _meeting(uid: str, start: datetime, end: datetime, subject: str = "Review") -> Meeting:
    return Meeting(uid=uid, subject=subject, start=start, end=end, mailbox="user@company.com")


class RefreshAndCacheTests(unittest.TestCase):
    def test_single_flight_blocks_overlapping_refresh(self) -> None:
        gate = SingleFlight()
        self.assertTrue(gate.try_acquire())
        self.assertFalse(gate.try_acquire())
        gate.release()
        self.assertTrue(gate.try_acquire())

    def test_join_reminder_opens_before_the_meeting_and_only_once(self) -> None:
        from app.services.join_reminders import due_reminders, reminder_key

        start = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
        meeting = _meeting("one", start, start + timedelta(minutes=30), "Daily Standup")
        now = start - timedelta(minutes=4)
        self.assertEqual([item.uid for item in due_reminders([meeting], now, 5, set())], ["one"])
        self.assertEqual(due_reminders([meeting], now, 5, {reminder_key(meeting)}), [])
        self.assertEqual(due_reminders([meeting], start - timedelta(minutes=6), 5, set()), [])
        self.assertEqual(due_reminders([meeting], now, 0, set()), [])
        meeting.busy_status = "free"
        self.assertEqual(due_reminders([meeting], now, 5, set()), [])
        meeting.busy_status = "busy"
        meeting.response_status = "declined"
        self.assertEqual(due_reminders([meeting], now, 5, set()), [])
        meeting.response_status = "accepted"
        meeting.is_all_day = True
        self.assertEqual(due_reminders([meeting], now, 5, set()), [])

    def test_interval_is_limited_to_five_or_ten_minutes(self) -> None:
        config = AppConfig.from_dict({"refresh_interval_minutes": 15, "auto_refresh": True})
        self.assertEqual(config.refresh_interval_minutes, 5)
        other = AppConfig.from_dict({"refresh_interval_minutes": "10"})
        self.assertEqual(other.refresh_interval_minutes, 10)

    def test_config_never_stores_a_password(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            config = AppConfig(email="user@company.com", username=r"DOMAIN\user", auth_method="basic")
            config.save(path)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("password", text.lower())
            self.assertNotIn("s3cret-password", text)
            loaded = load_config(path)
            self.assertEqual(loaded.email, "user@company.com")
            self.assertEqual(loaded.auth_method, "basic")
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_saved_account_is_encrypted(self) -> None:
        from app.storage.secrets import load_password, load_profile, save_credentials

        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            stored, warning = save_credentials(
                "user@company.com",
                "s3cret-password",
                {
                    "email": "user@company.com",
                    "username": r"DOMAIN\user",
                    "domain": "DOMAIN",
                    "ews_url": "https://exchange.company.com/EWS/Exchange.asmx",
                    "auth_method": "ntlm",
                },
                paths,
            )
            self.assertTrue(stored, warning)
            blob = (paths.data_dir / "credentials.vault").read_bytes()
            self.assertNotIn(b"s3cret-password", blob)
            self.assertNotIn(b"user@company.com", blob)
            self.assertEqual(load_password("user@company.com", paths), "s3cret-password")
            profile = load_profile("user@company.com", paths)
            self.assertEqual(profile["username"], r"DOMAIN\user")
            self.assertEqual(profile["ews_url"], "https://exchange.company.com/EWS/Exchange.asmx")

    def test_autostart_entry_can_be_enabled_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "exchange-calendar.desktop"
            set_launch_at_login(True, command="/usr/bin/python /opt/exchange-calendar/main.py", path=path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Exec=/usr/bin/python /opt/exchange-calendar/main.py", text)
            set_launch_at_login(False, path=path)
            self.assertFalse(path.exists())

    def test_cache_roundtrip_is_isolated_by_mailbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = CalendarCache(Path(temporary) / "cache.sqlite")
            start = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
            end = start + timedelta(hours=1)
            window_start = start - timedelta(days=1)
            window_end = end + timedelta(days=1)
            synced = datetime(2026, 11, 19, 6, 5, tzinfo=timezone.utc)
            first = _meeting("one", start, end, "Daily Standup")
            second = _meeting("two", start + timedelta(hours=2), end + timedelta(hours=2), "Review")
            second.mailbox = "other@company.com"
            cache.save_success(
                "user@company.com",
                [first],
                [],
                "not_configured",
                "Not configured",
                window_start,
                window_end,
                synced,
                60,
            )
            cache.save_success(
                "other@company.com",
                [second],
                [],
                "ok",
                "",
                window_start,
                window_end,
                synced,
                60,
            )
            loaded = cache.load("user@company.com")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual([item.subject for item in loaded.meetings], ["Daily Standup"])
            self.assertEqual(loaded.meetings[0].start, start)
            self.assertEqual(loaded.tasks_message, "Not configured")
            mode = stat.S_IMODE(cache.path.stat().st_mode)
            self.assertEqual(mode, 0o600)
            raw = cache.path.read_bytes()
            self.assertNotIn(b"s3cret-password", raw)

    def test_cache_replaces_meetings_inside_the_sync_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = CalendarCache(Path(temporary) / "cache.sqlite")
            start = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
            window_start = datetime(2026, 11, 1, tzinfo=timezone.utc)
            window_end = datetime(2026, 12, 1, tzinfo=timezone.utc)
            synced = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)
            original = _meeting("one", start, start + timedelta(hours=1), "Old Meeting")
            cache.save_success("user@company.com", [original], [], "ok", "", window_start, window_end, synced, 60)
            replacement = _meeting("two", start + timedelta(hours=3), start + timedelta(hours=4), "New Meeting")
            cache.save_success(
                "user@company.com",
                [replacement],
                [],
                "ok",
                "",
                window_start,
                window_end,
                synced,
                60,
            )
            loaded = cache.load("user@company.com")
            assert loaded is not None
            self.assertEqual([item.uid for item in loaded.meetings], ["two"])

    def test_failed_sync_keeps_the_cached_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = CalendarCache(root / "cache.sqlite")
            start = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
            cache.save_success(
                "user@company.com",
                [_meeting("one", start, start + timedelta(hours=1))],
                [],
                "ok",
                "",
                start - timedelta(days=1),
                start + timedelta(days=1),
                datetime.now(timezone.utc),
                60,
            )

            class DownClient:
                def __init__(self, config, password) -> None:
                    self.config = config

                def fetch(self, window_start, window_end, tz):
                    raise ExchangeError("The Exchange server did not respond.")

            config = AppConfig(
                email="user@company.com",
                username=r"DOMAIN\user",
                ews_url="https://exchange.company.com/EWS/Exchange.asmx",
                use_autodiscover=False,
            )
            request = SyncRequest(
                config=config,
                password="s3cret-password",
                demo=False,
                anchor=start,
            )
            snapshot = perform_sync(request, cache, client_factory=DownClient)
            self.assertTrue(snapshot.from_cache)
            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.meetings[0].subject, "Review")
            self.assertIn("did not respond", snapshot.error or "")
            self.assertNotIn("s3cret-password", repr(request))

    def test_missing_credentials_do_not_call_exchange(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = CalendarCache(Path(temporary) / "cache.sqlite")
            called = {"count": 0}

            class Unexpected:
                def __init__(self, config, password) -> None:
                    called["count"] += 1

                def fetch(self, *args, **kwargs):
                    called["count"] += 1
                    return [], [], "ok", ""

            request = SyncRequest(
                config=AppConfig(email="user@company.com", use_autodiscover=True),
                password="",
                demo=False,
                anchor=datetime(2026, 11, 19, tzinfo=timezone.utc),
            )
            snapshot = perform_sync(request, cache, client_factory=Unexpected)
            self.assertEqual(called["count"], 0)
            self.assertIn("not configured", snapshot.error.lower() if snapshot.error else "")
            self.assertEqual(snapshot.error, NOT_CONFIGURED)

    def test_logs_redact_passwords_and_authorization_headers(self) -> None:
        text = redact(
            "password=s3cret-password Authorization: NTLM abcdef https://user:s3cret-password@exchange.company.com/EWS"
        )
        self.assertNotIn("s3cret-password", text)
        self.assertIn("***", text)

    def test_paths_can_be_isolated_for_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            self.assertEqual(paths.config_file.parent, Path(temporary) / "config")
            self.assertEqual(paths.cache_file.parent, Path(temporary) / "data")


if __name__ == "__main__":
    unittest.main()
