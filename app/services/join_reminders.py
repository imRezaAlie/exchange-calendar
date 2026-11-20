"""Decide when a meeting should raise a join reminder. No mailbox access."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta

from app.calendar.date_utils import as_utc
from app.models import Meeting

REMINDER_MINUTES = (0, 2, 5, 10)


def normalize_reminder(minutes: object) -> int:
    try:
        value = int(minutes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 5
    return value if value in REMINDER_MINUTES else 5


def reminder_key(meeting: Meeting) -> str:
    return f"{meeting.uid}|{as_utc(meeting.start).isoformat()}"


def due_reminders(
    meetings: list[Meeting],
    now: datetime,
    lead_minutes: int,
    already_sent: set[str],
) -> list[Meeting]:
    if lead_minutes <= 0:
        return []
    due = [meeting for meeting in meetings if _is_due(meeting, now, lead_minutes, already_sent)]
    due.sort(key=lambda meeting: as_utc(meeting.start))
    return due


def play_reminder_sound() -> None:
    """Two short bells. Playback stays off the UI thread and adds no tray icon."""
    command = _sound_command()
    if command is None:
        return
    threading.Thread(target=_play_twice, args=(command,), daemon=True).start()


def _sound_command() -> list[str] | None:
    canberra = shutil.which("canberra-gtk-play")
    if canberra:
        return [canberra, "-i", "bell"]
    bell = "/usr/share/sounds/freedesktop/stereo/bell.oga"
    player = shutil.which("pw-play") or shutil.which("paplay")
    if player and os.path.isfile(bell):
        return [player, bell]
    return None


def _play_twice(command: list[str]) -> None:
    for _ in range(2):
        try:
            subprocess.run(
                command,
                check=False,
                timeout=3,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return


def post_desktop_notification(title: str, body: str) -> None:
    """GNOME notification. This does not create a tray icon."""
    if shutil.which("notify-send") is None or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    try:
        subprocess.run(
            ["notify-send", "--app-name=Exchange Calendar", "--urgency=normal", title[:120], body[:240]],
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def post_alarm_notification(title: str, body: str, actions: list[tuple[str, str]], on_action) -> None:
    """Show a notification. Action clicks are reported when the desktop supports them."""
    if shutil.which("notify-send") is None or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    help_text = _notify_send_help()
    command = ["notify-send", "--app-name=Exchange Calendar", "--urgency=normal"]
    if "--expire-time" in help_text:
        command.extend(["--expire-time=0"])
    if actions and "--action" in help_text:
        if "--wait" in help_text:
            command.append("--wait")
        for key, label in actions:
            command.extend(["--action", f"{key}={label}"])
    command.extend([title[:120], body[:240]])

    def _deliver() -> None:
        try:
            result = subprocess.run(
                command,
                check=False,
                timeout=600,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        chosen = (result.stdout or "").strip()
        if chosen and on_action is not None:
            try:
                on_action(chosen)
            except Exception:
                return

    threading.Thread(target=_deliver, daemon=True).start()


def _notify_send_help() -> str:
    cached = getattr(_notify_send_help, "value", None)
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            ["notify-send", "--help"],
            check=False,
            timeout=2,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        cached = result.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        cached = ""
    setattr(_notify_send_help, "value", cached)
    return cached


def _is_due(meeting: Meeting, now: datetime, lead_minutes: int, already_sent: set[str]) -> bool:
    if reminder_key(meeting) in already_sent:
        return False
    if meeting.is_cancelled or meeting.is_all_day:
        return False
    if meeting.response_status == "declined" or meeting.busy_status == "free":
        return False
    start = as_utc(meeting.start)
    end = as_utc(meeting.end)
    moment = as_utc(now)
    if moment >= end:
        return False
    opens = start - timedelta(minutes=lead_minutes)
    closes = start + timedelta(seconds=45)
    return opens <= moment <= closes
