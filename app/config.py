"""Persistent preferences. Passwords are never written here."""

from __future__ import annotations

import json
import logging
import os
import shlex
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "exchange-calendar"
ALLOWED_INTERVALS = (5, 10)
AUTH_METHODS = ("ntlm", "basic", "kerberos")
VIEWS = ("daily", "weekly", "monthly", "agenda")
WEEK_STARTS = ("monday", "sunday")
THEMES = ("light", "dark")


def normalize_interval(minutes: int) -> int:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return 5
    return value if value in ALLOWED_INTERVALS else 5


class AppPaths:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    @property
    def config_dir(self) -> Path:
        if self.root is not None:
            return self.root / "config"
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / APP_NAME

    @property
    def data_dir(self) -> Path:
        if self.root is not None:
            return self.root / "data"
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return base / APP_NAME

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def cache_file(self) -> Path:
        return self.data_dir / "cache.sqlite"

    @property
    def log_file(self) -> Path:
        if self.root is not None:
            return self.root / "state" / "exchange-calendar.log"
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        return base / APP_NAME / "exchange-calendar.log"


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, int):
        return bool(value)
    return default


@dataclass(slots=True)
class AppConfig:
    email: str = ""
    username: str = ""
    domain: str = ""
    ews_url: str = ""
    auth_method: str = "ntlm"
    use_autodiscover: bool = True
    timezone: str = ""
    default_view: str = "weekly"
    week_starts_on: str = "monday"
    show_cancelled: bool = False
    show_all_day: bool = True
    auto_refresh: bool = True
    refresh_interval_minutes: int = 5
    highlight_conflicts: bool = True
    include_tentative_conflicts: bool = True
    include_all_day_conflicts: bool = False
    start_minimized: bool = False
    minimize_to_tray: bool = False
    launch_at_login: bool = False
    join_reminder_minutes: int = 5
    meeting_reminder_offsets: list[int] = field(default_factory=lambda: [10, 0])
    reminders_enabled: bool = True
    alarm_sound_enabled: bool = True
    desktop_notifications_enabled: bool = True
    alarm_popup_enabled: bool = True
    alarm_volume: int = 70
    alarm_sound: str = "classic"
    alarms_muted: bool = False
    meeting_reminders_enabled: bool = True
    conflict_alarm_warnings: bool = True
    respect_exchange_reminder: bool = False
    todo_reminders_enabled: bool = True
    default_task_reminder_time: str = "09:00"
    overdue_reminders_enabled: bool = True
    carry_forward_reminders: bool = True
    daily_todo_summary: bool = False
    snooze_enabled: bool = True
    default_snooze_minutes: int = 5
    max_repeated_reminders: int = 2
    connection_open: bool = False
    theme: str = "light"
    ca_bundle: str = ""
    cache_retention_days: int = 60

    def account_key(self) -> str:
        return (self.email or self.username).strip()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("password", None)
        return payload

    def normalized(self) -> AppConfig:
        self.email = self.email.strip()
        self.username = self.username.strip()
        self.domain = self.domain.strip()
        self.ews_url = self.ews_url.strip()
        self.timezone = self.timezone.strip()
        self.ca_bundle = self.ca_bundle.strip()
        self.auth_method = self.auth_method.strip().lower()
        if self.auth_method not in AUTH_METHODS:
            self.auth_method = "ntlm"
        self.default_view = self.default_view if self.default_view in VIEWS else "weekly"
        self.week_starts_on = self.week_starts_on if self.week_starts_on in WEEK_STARTS else "monday"
        self.refresh_interval_minutes = normalize_interval(self.refresh_interval_minutes)
        try:
            reminder = int(self.join_reminder_minutes)
        except (TypeError, ValueError):
            reminder = 5
        self.join_reminder_minutes = reminder if reminder in (0, 2, 5, 10) else 5
        from app.services.alarm_sound import SOUNDS
        from app.services.alarms import normalize_offsets

        if not isinstance(self.meeting_reminder_offsets, list):
            self.meeting_reminder_offsets = [10, 0]
        self.meeting_reminder_offsets = normalize_offsets(self.meeting_reminder_offsets)
        self.alarm_sound = self.alarm_sound if self.alarm_sound in SOUNDS else "classic"
        try:
            volume = int(self.alarm_volume)
        except (TypeError, ValueError):
            volume = 70
        self.alarm_volume = min(100, max(0, volume))
        try:
            snooze = int(self.default_snooze_minutes)
        except (TypeError, ValueError):
            snooze = 5
        self.default_snooze_minutes = snooze if snooze in (5, 10, 15, 30) else 5
        try:
            repeats = int(self.max_repeated_reminders)
        except (TypeError, ValueError):
            repeats = 2
        self.max_repeated_reminders = min(4, max(1, repeats))
        clock = str(self.default_task_reminder_time or "09:00")
        parts = clock.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                self.default_task_reminder_time = f"{hour:02d}:{minute:02d}"
            else:
                self.default_task_reminder_time = "09:00"
        else:
            self.default_task_reminder_time = "09:00"
        self.theme = self.theme if self.theme in THEMES else "light"
        try:
            days = int(self.cache_retention_days)
        except (TypeError, ValueError):
            days = 60
        self.cache_retention_days = min(180, max(7, days))
        return self

    @classmethod
    def from_dict(cls, payload: dict) -> AppConfig:
        boolean_fields = {
            "use_autodiscover",
            "show_cancelled",
            "show_all_day",
            "auto_refresh",
            "highlight_conflicts",
            "include_tentative_conflicts",
            "include_all_day_conflicts",
            "start_minimized",
            "minimize_to_tray",
            "launch_at_login",
            "connection_open",
            "reminders_enabled",
            "alarm_sound_enabled",
            "desktop_notifications_enabled",
            "alarm_popup_enabled",
            "alarms_muted",
            "meeting_reminders_enabled",
            "conflict_alarm_warnings",
            "respect_exchange_reminder",
            "todo_reminders_enabled",
            "overdue_reminders_enabled",
            "carry_forward_reminders",
            "daily_todo_summary",
            "snooze_enabled",
        }
        known = {item.name for item in fields(cls)}
        values: dict = {}
        for key, value in payload.items():
            if key not in known or key == "password":
                continue
            if key in boolean_fields:
                default = getattr(cls(), key)
                values[key] = _as_bool(value, default)
            else:
                values[key] = value
        missing_offsets = "meeting_reminder_offsets" not in payload
        config = cls(**values).normalized()
        if missing_offsets:
            from app.services.alarms import normalize_offsets

            legacy = config.join_reminder_minutes
            config.meeting_reminder_offsets = normalize_offsets([legacy] if legacy else [])
        return config

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            log.warning("Could not restrict the configuration directory permissions.")
        payload = self.normalized().to_dict()
        if "password" in payload:
            raise RuntimeError("Refusing to write a password into the configuration file.")
        text = json.dumps(payload, indent=2)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(text + "\n", encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            log.warning("Could not restrict the temporary configuration file permissions.")
        temporary.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            log.warning("Could not restrict the configuration file permissions.")


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("The configuration file could not be read. Defaults will be used.")
        return AppConfig()
    if not isinstance(payload, dict):
        log.error("The configuration file is not a JSON object. Defaults will be used.")
        return AppConfig()
    try:
        return AppConfig.from_dict(payload)
    except Exception:
        log.exception("The configuration file could not be applied. Defaults will be used.")
        return AppConfig()


def default_launch_command() -> str:
    if getattr(sys, "frozen", False):
        return shlex.quote(sys.executable)
    main = Path(__file__).resolve().parents[1] / "main.py"
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(main))}"


def autostart_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / "exchange-calendar.desktop"


def set_launch_at_login(enabled: bool, command: str | None = None, path: Path | None = None) -> None:
    destination = path or autostart_file()
    if not enabled:
        if destination.exists():
            destination.unlink()
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    launch = command or default_launch_command()
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=Exchange Calendar\n"
        "Comment=Outlook Today style Exchange calendar\n"
        f"Exec={launch}\n"
        "Icon=exchange-calendar\n"
        "Terminal=false\n"
        "Categories=Office;Calendar;\n"
        "StartupWMClass=exchange-calendar\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    destination.write_text(content, encoding="utf-8")
    try:
        os.chmod(destination, 0o644)
    except OSError:
        log.warning("Could not set permissions on the autostart entry.")
