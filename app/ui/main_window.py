"""Agenda window: date header, calendar, connection column, and status."""

from __future__ import annotations

import logging
from datetime import datetime, time

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QSizePolicy,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.calendar.conflict_detector import ConflictPolicy, detect_conflicts
from app.calendar.date_utils import format_long_date, resolve_timezone
from app.config import AppConfig, AppPaths, load_config, set_launch_at_login
from app.logging_config import register_secret
from app.models import Meeting, SyncSnapshot
from app.services.alarm_sound import play_alarm
from app.services.alarms import (
    carry_forward,
    due_meeting_alarms,
    due_snoozes,
    due_summary,
    due_todo_alarms,
    make_snooze,
    next_trigger,
)
from app.services.join_reminders import post_alarm_notification
from app.services.notification_service import NotificationService
from app.services.refresh_service import RefreshService
from app.services.sync import SyncRequest
from app.storage.cache import CalendarCache
from app.storage.secrets import delete_password, load_password, load_profile, save_credentials
from app.ui.calendar_widget import CalendarWidget
from app.ui.colors import colors
from app.ui.context_panels import ConflictPanel, EventDetailsPanel
from app.ui.icons import (
    bell_icon,
    calendar_icon,
    chevron_icon,
    gear_icon,
    messages_icon,
    refresh_icon,
    tasks_icon,
)

_COLLAPSED_CONNECTION_WIDTH = 48
from app.storage.reminders import ReminderStore
from app.ui.alarm_popup import AlarmPopup
from app.ui.reminders_panel import ReminderPanel
from app.ui.todo_dialog import TodoDialog
from app.ui.todo_panel import TodoPanel
from app.ui.theme import apply_theme
from app.ui.widgets import make_button
from app.ui.meeting_details import MeetingDetailsDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.side_panels import MessagesPanel

log = logging.getLogger(__name__)


class _ColumnHeader(QWidget):
    def __init__(self, title: str, icon: QIcon, *, collapsible: bool = False) -> None:
        super().__init__()
        self.setObjectName("columnHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(8)
        self._image = QLabel()
        self._image.setPixmap(icon.pixmap(16, 16))
        self._text = QLabel(title)
        self._text.setObjectName("columnHeaderText")
        layout.addWidget(self._image)
        layout.addWidget(self._text, 1)
        self.toggle_button: QPushButton | None = None
        if collapsible:
            self.toggle_button = make_button("", "icon")
            self.toggle_button.setToolTip("Hide connection")
            layout.addWidget(self.toggle_button)

    def set_icon(self, icon: QIcon) -> None:
        self._image.setPixmap(icon.pixmap(16, 16))

    def set_title(self, title: str) -> None:
        self._text.setText(title)


class _AlarmActions(QObject):
    chosen = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(self, demo: bool = False, paths: AppPaths | None = None) -> None:
        super().__init__()
        self._demo = demo
        self.paths = paths or AppPaths()
        self.config = load_config(self.paths.config_file)
        self._password = ""
        if not demo:
            self._restore_account()
        if self._password:
            register_secret(self._password)
        self._tz = resolve_timezone(self.config.timezone)
        self._snapshot: SyncSnapshot | None = None
        self._busy = False
        self._force_quit = False
        self._tray_hint_shown = False
        self._sizes_initialized = False
        self._closing = False
        self._connection_open = self.config.connection_open
        self._connection_width = 300
        self._connection_anim: QVariantAnimation | None = None
        self._connection_animating = False
        self.tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._selected_meeting: Meeting | None = None
        self._alarm_popup: AlarmPopup | None = None
        self._alarm_queue: list = []
        self._todo_dialog: TodoDialog | None = None
        self.reminders = ReminderStore(self.paths.data_dir)
        self._alarm_actions = _AlarmActions(self)
        self._alarm_actions.chosen.connect(self._on_notification_action)
        self._auto_action = None

        self.setWindowTitle("Exchange Calendar — Demo" if demo else "Exchange Calendar")
        self.setWindowIcon(calendar_icon(64))
        self.resize(1280, 800)
        self.setMinimumSize(960, 640)

        self.cache = CalendarCache(self.paths.cache_file)
        self.refresh_service = RefreshService(self.cache, self)
        self.refresh_service.set_request_factory(self._make_request)
        self.refresh_service.snapshot_ready.connect(self._on_snapshot)
        self.refresh_service.busy_changed.connect(self._on_busy)
        self.refresh_service.refresh_skipped.connect(self._on_refresh_skipped)

        self._build_ui()
        self._sync_tray()
        self.notifications = NotificationService(self.tray)
        self._install_shortcuts()
        self._update_header()
        self.messages.set_auto(self.config.auto_refresh)
        self.messages.set_interval(self.config.refresh_interval_minutes)
        self._render()

        self._clock = QTimer(self)
        self._clock.setInterval(60_000)
        self._clock.timeout.connect(self._on_clock)
        self._clock.start()
        self._alarm_timer = QTimer(self)
        self._alarm_timer.setInterval(30_000)
        self._alarm_timer.timeout.connect(self._check_alarms)
        self._alarm_timer.start()

        self.refresh_service.apply_timer(self.config.auto_refresh, self.config.refresh_interval_minutes)
        self.refresh_service.refresh_now()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.calendar = CalendarWidget(
            self._tz,
            self.config.week_starts_on,
            self.config.default_view,
        )
        self.calendar._highlight = self.config.highlight_conflicts
        self.calendar.meeting_selected.connect(self._open_meeting)
        self.calendar.task_selected.connect(self._reveal_task)
        self.calendar.anchor_changed.connect(self._on_anchor_changed)
        self.calendar.conflicts_requested.connect(lambda: self._open_context("conflicts"))
        self.messages = MessagesPanel()
        self._details = EventDetailsPanel()
        self._details.full_details_requested.connect(self._open_full_details)
        self._conflicts = ConflictPanel()
        self._conflicts.meeting_chosen.connect(self._focus_conflict)
        self.messages.auto_refresh_changed.connect(self._on_auto_toggled)
        self.messages.interval_changed.connect(self._on_interval_changed)
        self.messages.refresh_requested.connect(self.refresh_service.refresh_now)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.addWidget(self._build_dashboard())
        self._status_header = _ColumnHeader(
            "Connection",
            messages_icon(16, colors()["accent"]),
            collapsible=True,
        )
        assert self._status_header.toggle_button is not None
        self._status_header.toggle_button.clicked.connect(self._toggle_connection)
        expanded = QWidget()
        expanded_layout = QVBoxLayout(expanded)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        expanded_layout.setSpacing(0)
        expanded_layout.addWidget(self._status_header)
        self._context_pages = QStackedWidget()
        self._context_pages.addWidget(self.todo_board)
        self._context_pages.addWidget(self.reminder_board)
        self._context_pages.addWidget(self._details)
        self._context_pages.addWidget(self._conflicts)
        self._context_pages.addWidget(self.messages)
        self._context_mode = "sync"
        self._context_pages.setCurrentIndex(4)
        expanded_layout.addWidget(self._context_pages, 1)
        self._connection_rail = self._build_connection_rail()
        self._connection_stack = QStackedWidget()
        self._connection_stack.addWidget(expanded)
        self._connection_stack.addWidget(self._connection_rail)
        status_pane = QWidget()
        status_layout = QVBoxLayout(status_pane)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)
        status_layout.addWidget(self._connection_stack)
        self._status_pane = status_pane
        if self._connection_open:
            status_pane.setMinimumWidth(280)
            self._connection_stack.setCurrentIndex(0)
        else:
            status_pane.setMinimumWidth(_COLLAPSED_CONNECTION_WIDTH)
            status_pane.setMaximumWidth(_COLLAPSED_CONNECTION_WIDTH)
            self._connection_stack.setCurrentIndex(1)
        splitter.addWidget(status_pane)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        self.splitter = splitter
        self._style_connection_drawer()
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self._status = QLabel()
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.statusBar().addWidget(self._status, 1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("topHeader")
        header.setFixedHeight(52)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(calendar_icon(28).pixmap(28, 28))
        mark.setFixedSize(28, 28)
        caption = QLabel("Exchange Calendar")
        caption.setObjectName("appCaption")
        self.date_label = QLabel()
        self.date_label.setObjectName("todayDate")
        layout.addWidget(mark)
        layout.addWidget(caption)
        layout.addWidget(self.date_label)
        if self._demo:
            badge = QLabel("DEMO")
            badge.setObjectName("demoBadge")
            layout.addWidget(badge)
        if self.config.email:
            account = QLabel(self.config.email)
            account.setObjectName("todayDate")
            layout.addWidget(account)
        layout.addStretch(1)
        self.settings_button = make_button("", "icon", gear_icon(16, colors()["text"]))
        self.refresh_button = make_button("", "icon", refresh_icon(16, colors()["text"]))
        self.settings_button.setToolTip("Settings (Ctrl+,)")
        self.refresh_button.setToolTip("Refresh the calendar (F5)")
        self.settings_button.clicked.connect(self.open_settings)
        self.refresh_button.clicked.connect(self.refresh_service.refresh_now)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.refresh_button)
        self._style_chrome()
        return header

    def _style_chrome(self) -> None:
        palette = colors()
        self.settings_button.setIcon(gear_icon(16, palette["text"]))
        icon_color = palette["disabled_text"] if self._busy else palette["text"]
        self.refresh_button.setIcon(refresh_icon(16, icon_color))
        header = getattr(self, "_status_header", None)
        if header is not None:
            header.set_icon(messages_icon(16, palette["text"]))
        if hasattr(self, "reminder_board"):
            self.reminder_board.refresh_icons()
        self._style_connection_drawer()

    def _apply_visual_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.config.theme)
        self._style_chrome()
        if hasattr(self, "calendar"):
            self.calendar.refresh_icons()
        self._render()

    def _build_dashboard(self) -> QWidget:
        self.todo_board = TodoPanel(
            self.reminders,
            datetime.now(self._tz).date(),
            self.config.default_task_reminder_time,
        )
        self.todo_board.changed.connect(self._on_todos_changed)
        self.reminder_board = ReminderPanel()
        self.reminder_board.setMaximumHeight(16777215)
        calendar_column = QWidget()
        calendar_layout = QVBoxLayout(calendar_column)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        calendar_layout.setSpacing(0)
        calendar_layout.addWidget(self.calendar, 1)
        calendar_column.setMinimumWidth(520)
        return calendar_column

    def _install_shortcuts(self) -> None:
        bindings = (
            ("Ctrl+Left", self.calendar.go_previous),
            ("Alt+Left", self.calendar.go_previous),
            ("Ctrl+Right", self.calendar.go_next),
            ("Alt+Right", self.calendar.go_next),
            ("Ctrl+T", self.calendar.go_today),
            ("F5", self.refresh_service.refresh_now),
            ("Ctrl+R", self.refresh_service.refresh_now),
            ("Ctrl+,", self.open_settings),
            ("Ctrl+1", lambda: self.calendar.set_view("daily")),
            ("Ctrl+2", lambda: self.calendar.set_view("weekly")),
            ("Ctrl+3", lambda: self.calendar.set_view("monthly")),
            ("Ctrl+4", lambda: self.calendar.set_view("agenda")),
        )
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)

    def _create_tray(self) -> None:
        try:
            available = QSystemTrayIcon.isSystemTrayAvailable()
        except Exception:
            available = False
        if not available:
            log.info("The system tray is not available. Minimize will use the normal window.")
            return
        self.tray = QSystemTrayIcon(calendar_icon(32), self)
        self.tray.setToolTip("Exchange Calendar")
        # Leave the menu unparented. Parenting it to this window destroys the
        # menu while Exit is still handling the click, and the shutdown is dropped.
        menu = QMenu()
        self._tray_menu = menu
        menu.addAction("Open Calendar", self.show_normal)
        menu.addAction("Refresh Now", self.refresh_service.refresh_now)
        self._auto_action = menu.addAction("Auto Refresh")
        self._auto_action.setCheckable(True)
        self._auto_action.setChecked(self.config.auto_refresh)
        self._auto_action.toggled.connect(self._on_auto_toggled)
        menu.addAction("Settings", self.open_settings)
        menu.addAction("Tasks", self.open_todos)
        self._mute_action = menu.addAction("Mute Alarms")
        self._mute_action.setCheckable(True)
        self._mute_action.setChecked(self.config.alarms_muted)
        self._mute_action.toggled.connect(self._on_mute_toggled)
        menu.addAction("Snooze All Reminders", self._snooze_all)
        menu.addSeparator()
        menu.addAction("Exit", self.quit_application)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _sync_tray(self) -> None:
        wants_tray = self.config.minimize_to_tray or self.config.start_minimized
        if wants_tray and self.tray is None:
            self._create_tray()
        if self.tray is not None:
            self.tray.setVisible(wants_tray and QSystemTrayIcon.isSystemTrayAvailable())
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(not self._minimize_on_close())

    def _remove_tray(self) -> None:
        menu = self._tray_menu
        self._tray_menu = None
        if menu is not None:
            menu.hide()
            menu.deleteLater()
        if self.tray is None:
            return
        self.tray.hide()
        self.tray.setContextMenu(None)
        self.tray.setVisible(False)

    def _make_request(self) -> SyncRequest:
        anchor = datetime.combine(self.calendar.anchor, time.min, tzinfo=self._tz)
        return SyncRequest(config=self.config, password=self._password, demo=self._demo, anchor=anchor)

    def _visible_meeting(self, meeting: Meeting) -> bool:
        if meeting.is_cancelled and not self.config.show_cancelled:
            return False
        if meeting.is_all_day and not self.config.show_all_day:
            return False
        return True

    def _on_snapshot(self, snapshot: SyncSnapshot) -> None:
        previous = self._snapshot
        self._snapshot = snapshot
        self._render()
        if snapshot.demo or not self.config.email:
            return
        if snapshot.error and (previous is None or previous.error != snapshot.error):
            self.notifications.sync_failed(snapshot.error)
        elif previous and previous.error and not snapshot.error and snapshot.connected:
            self.notifications.sync_recovered()

    def _on_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh_button.setEnabled(not busy)
        icon_color = colors()["disabled_text"] if busy else colors()["text"]
        self.refresh_button.setIcon(refresh_icon(16, icon_color))
        self.messages.set_busy(busy)
        if busy:
            self.statusBar().showMessage("Refreshing calendar…", 3000)
        self._render_status()

    def _on_refresh_skipped(self) -> None:
        self.statusBar().showMessage("Refresh already in progress", 3000)

    def _on_anchor_changed(self) -> None:
        if self._snapshot is not None and self.calendar.outside_synced_window():
            self.refresh_service.refresh_now()

    def _on_clock(self) -> None:
        self._update_header()
        if self._snapshot is not None:
            self.calendar.rebuild(reset_scroll=False)
        self._render_status()
        self.messages.set_status(
            self._snapshot,
            self.refresh_service.next_refresh_at(),
            self.config,
            self._busy,
            self._tz,
        )
        self._refresh_reminders()
        self._check_join_reminders()

    def _render(self) -> None:
        snapshot = self._snapshot
        self.messages.set_status(
            snapshot,
            self.refresh_service.next_refresh_at(),
            self.config,
            self._busy,
            self._tz,
        )
        self.calendar.set_todos(self.reminders.todos, rebuild=False)
        if snapshot is None:
            self.calendar.set_empty_reason("Loading calendar…")
            self.calendar.set_meetings([], detect_conflicts([]), None, None, reset_scroll=False)
            self._render_status()
            return
        displayed = [meeting for meeting in snapshot.meetings if self._visible_meeting(meeting)]
        policy = ConflictPolicy(
            include_tentative=self.config.include_tentative_conflicts,
            include_all_day=self.config.include_all_day_conflicts,
        )
        report = detect_conflicts(displayed, policy)
        if snapshot.meetings:
            self.calendar.set_empty_reason("")
        else:
            self.calendar.set_empty_reason(snapshot.error or "No meetings in the synchronized range.")
        self.calendar.set_meetings(
            displayed,
            report,
            snapshot.window_start,
            snapshot.window_end,
            reset_scroll=False,
        )
        if snapshot.from_cache and snapshot.synced_at is not None:
            when = snapshot.synced_at.astimezone(self._tz).strftime("%H:%M")
            self.calendar.set_banner(
                f"Showing cached meetings from the last successful sync at {when}. Exchange is unavailable."
            )
        else:
            self.calendar.set_banner("")
        self._render_status()
        self._refresh_reminders()
        self._refresh_conflicts()
        self._check_join_reminders()

    def _check_join_reminders(self) -> None:
        self._check_alarms()

    def _check_alarms(self) -> None:
        now = datetime.now(self._tz)
        if carry_forward(self.reminders.todos, now.date(), self.config.carry_forward_reminders):
            self.reminders.save()
            self.calendar.set_todos(self.reminders.todos)
            if hasattr(self, "todo_board"):
                self.todo_board.reload()
            if self._todo_dialog is not None and self._todo_dialog.isVisible():
                self._todo_dialog.reload()
        if not self.config.reminders_enabled:
            self._update_tray_tip(now)
            return
        held = {alarm.key for alarm in self._alarm_queue}
        if self._alarm_popup is not None and self._alarm_popup.isVisible():
            held.add(self._alarm_popup.alarm.key)
        fired = set(self.reminders.fired) | held
        alarms = due_snoozes(self.reminders.snoozes, now, fired)
        if self._snapshot is not None and (self.config.meeting_reminders_enabled or self.config.join_reminder_minutes > 0):
            visible = [meeting for meeting in self._snapshot.meetings if self._visible_meeting(meeting)]
            alarms.extend(
                due_meeting_alarms(
                    visible,
                    now,
                    list(self.config.meeting_reminder_offsets) if self.config.meeting_reminders_enabled else [],
                    fired,
                    respect_exchange=self.config.respect_exchange_reminder and self.config.meeting_reminders_enabled,
                    conflict_warnings=self.config.conflict_alarm_warnings,
                    conflict_policy=ConflictPolicy(
                        include_tentative=self.config.include_tentative_conflicts,
                        include_all_day=self.config.include_all_day_conflicts,
                    ),
                    cached=bool(self._snapshot.from_cache),
                    join_minutes=int(self.config.join_reminder_minutes),
                )
            )
        alarms.extend(
            due_todo_alarms(
                self.reminders.todos,
                now,
                self._tz,
                fired,
                enabled=self.config.todo_reminders_enabled,
                overdue=self.config.overdue_reminders_enabled,
            )
        )
        summary = due_summary(
            self.reminders.todos,
            now,
            self._tz,
            fired,
            enabled=self.config.daily_todo_summary,
        )
        if summary is not None:
            alarms.append(summary)
        if alarms:
            self._present_alarms(alarms, now)
        self._update_tray_tip(now)

    def _present_alarms(self, alarms, now: datetime) -> None:
        self._alarm_queue.extend(alarms)
        if self.config.desktop_notifications_enabled:
            for alarm in alarms:
                post_alarm_notification(
                    _alarm_title(alarm),
                    _alarm_body(alarm, self._tz, now),
                    _notification_actions(alarm, int(self.config.default_snooze_minutes)),
                    lambda action, key=alarm.key: self._alarm_actions.chosen.emit(key, action),
                )
        if self.config.alarm_sound_enabled and not self.config.alarms_muted:
            repeats = 1
            if any(alarm.conflict_name for alarm in alarms):
                repeats = max(1, int(self.config.max_repeated_reminders))
            play_alarm(
                self.paths.data_dir / "sounds",
                self.config.alarm_sound,
                int(self.config.alarm_volume),
                repeats,
            )
        if self.config.alarm_popup_enabled:
            self._show_next_alarm()
            return
        self.reminders.mark_fired([alarm.key for alarm in alarms])
        self._alarm_queue.clear()

    def _show_next_alarm(self, *_ignored) -> None:
        if self._alarm_popup is not None and self._alarm_popup.isVisible():
            return
        if not self._alarm_queue:
            return
        alarm = self._alarm_queue.pop(0)
        self.reminders.mark_fired([alarm.key])
        popup = AlarmPopup(alarm, self._tz, datetime.now(self._tz), self.config.snooze_enabled, self)
        popup.snoozed.connect(self._on_alarm_snoozed)
        popup.completed.connect(self._on_alarm_completed)
        popup.details_requested.connect(self._on_alarm_details)
        popup.finished.connect(self._show_next_alarm)
        self._alarm_popup = popup
        popup.show()
        popup.raise_()

    def _on_alarm_snoozed(self, alarm, minutes: int) -> None:
        if not self.config.snooze_enabled:
            return
        self.reminders.add_snooze(make_snooze(alarm, int(minutes), datetime.now(self._tz)))
        self._update_tray_tip(datetime.now(self._tz))

    def _on_alarm_completed(self, alarm) -> None:
        if alarm.kind == "todo":
            self.reminders.complete(alarm.source_id)
            if hasattr(self, "todo_board"):
                self.todo_board.reload()
            self.calendar.set_todos(self.reminders.todos)
            if self._todo_dialog is not None and self._todo_dialog.isVisible():
                self._todo_dialog.reload()

    def _on_notification_action(self, key: str, action: str) -> None:
        alarm = None
        queued_index = None
        visible = self._alarm_popup is not None and self._alarm_popup.isVisible() and self._alarm_popup.alarm.key == key
        if visible:
            alarm = self._alarm_popup.alarm
        else:
            for index, item in enumerate(self._alarm_queue):
                if item.key == key:
                    alarm = item
                    queued_index = index
                    break
        if alarm is None:
            return
        if action == "join":
            if alarm.url:
                from app.ui.meeting_details import _open_http_url

                _open_http_url(alarm.url)
            return
        if queued_index is not None:
            self._alarm_queue.pop(queued_index)
        self.reminders.mark_fired([alarm.key])
        if visible and self._alarm_popup is not None:
            self._alarm_popup.blockSignals(True)
            self._alarm_popup.close()
            self._alarm_popup.blockSignals(False)
        if action == "snooze":
            self._on_alarm_snoozed(alarm, int(self.config.default_snooze_minutes))
        elif action == "done":
            self._on_alarm_completed(alarm)
        elif action in {"open", "conflict"}:
            self._on_alarm_details(alarm)
        self._show_next_alarm()

    def _on_alarm_details(self, alarm) -> None:
        if alarm.kind == "todo":
            self.open_todos(alarm.source_id)
            return
        if self._snapshot is None:
            return
        meeting = next((item for item in self._snapshot.meetings if item.uid == alarm.source_id), None)
        if meeting is not None:
            self._open_meeting(meeting)

    def _snooze_all(self) -> None:
        if not self.config.snooze_enabled:
            return
        now = datetime.now(self._tz)
        pending = list(self._alarm_queue)
        if self._alarm_popup is not None and self._alarm_popup.isVisible():
            pending.insert(0, self._alarm_popup.alarm)
        for alarm in pending:
            if alarm.kind == "summary":
                continue
            self.reminders.add_snooze(make_snooze(alarm, self.config.default_snooze_minutes, now))
        self._alarm_queue.clear()
        if self._alarm_popup is not None:
            self._alarm_popup.blockSignals(True)
            self._alarm_popup.close()
            self._alarm_popup.blockSignals(False)
        self._update_tray_tip(now)

    def _on_mute_toggled(self, muted: bool) -> None:
        self.config.alarms_muted = bool(muted)
        self._persist_config()
        if self._mute_action is not None:
            self._mute_action.blockSignals(True)
            self._mute_action.setChecked(self.config.alarms_muted)
            self._mute_action.blockSignals(False)

    def open_todos(self, uid: str = "") -> None:
        if isinstance(uid, bool):
            uid = ""
        if uid and hasattr(self, "todo_board"):
            self.todo_board.select(uid)
        if self._todo_dialog is None:
            self._todo_dialog = TodoDialog(
                self.reminders,
                datetime.now(self._tz).date(),
                self.config.default_task_reminder_time,
                self,
            )
            self._todo_dialog.changed.connect(self._on_todos_changed)
        self._todo_dialog.reload()
        if uid:
            self._todo_dialog.select_uid(uid)
        self._todo_dialog.show()
        self._todo_dialog.raise_()
        self._todo_dialog.activateWindow()

    def _on_todos_changed(self) -> None:
        self.calendar.set_todos(self.reminders.todos)
        if hasattr(self, "todo_board"):
            self.todo_board.set_today(datetime.now(self._tz).date())
            self.todo_board.set_default_time(self.config.default_task_reminder_time)
            self.todo_board.reload()
        self._refresh_reminders()
        self._check_alarms()

    def _update_tray_tip(self, now: datetime) -> None:
        if self.tray is None:
            return
        upcoming = next_trigger(
            [meeting for meeting in self._snapshot.meetings if self._visible_meeting(meeting)] if self._snapshot else [],
            self.reminders.todos,
            self.reminders.snoozes,
            now,
            self._tz,
            list(self.config.meeting_reminder_offsets) if self.config.meeting_reminders_enabled else [],
            self.reminders.fired,
            join_minutes=int(self.config.join_reminder_minutes),
        )
        if upcoming is None:
            self.tray.setToolTip("Exchange Calendar")
            return
        self.tray.setToolTip(f"Exchange Calendar\nNext reminder {upcoming.astimezone(self._tz).strftime('%H:%M')}")

    def _render_status(self) -> None:
        snapshot = self._snapshot
        next_at = self.refresh_service.next_refresh_at()
        next_text = next_at.astimezone(self._tz).strftime("%H:%M") if next_at else "—"
        auto = "On" if self.config.auto_refresh else "Off"
        palette = colors()
        if snapshot is None:
            state = f"<span style='color:{palette['starting']}'>Starting</span>"
            last = "—"
            self._set_connection("Starting", "quiet")
        elif snapshot.demo:
            state = f"<span style='color:{palette['demo']}'>Demo mode</span>"
            last = snapshot.synced_at.astimezone(self._tz).strftime("%H:%M") if snapshot.synced_at else "—"
            self._set_connection("Demo", "quiet")
        elif snapshot.connected and not snapshot.from_cache:
            state = f"<span style='color:{palette['connected']}'>Connected ●</span>"
            last = snapshot.synced_at.astimezone(self._tz).strftime("%H:%M") if snapshot.synced_at else "—"
            self._set_connection("Connected", "ok")
        elif snapshot.from_cache:
            state = f"<span style='color:{palette['danger']}'>Unavailable ●</span>"
            last = snapshot.synced_at.astimezone(self._tz).strftime("%H:%M") if snapshot.synced_at else "—"
            last = f"{last} (cached)"
            self._set_connection("Offline", "bad")
        else:
            state = f"<span style='color:{palette['danger']}'>Not connected ●</span>"
            last = "—"
            self._set_connection("Not connected", "bad")
        self._status.setText(
            f"Exchange: {state}&nbsp;&nbsp;&nbsp;Last sync: {last}"
            f"&nbsp;&nbsp;&nbsp;Next refresh: {next_text}&nbsp;&nbsp;&nbsp;Auto refresh: {auto}"
        )

    def _set_connection(self, text: str, tone: str) -> None:
        label = getattr(self, "connection_label", None)
        if label is None:
            return
        label.setText(text)
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_reminders(self) -> None:
        board = getattr(self, "reminder_board", None)
        if board is None:
            return
        meetings: list[Meeting] = []
        conflict_ids: set[str] = set()
        if self._snapshot is not None:
            meetings = [item for item in self._snapshot.meetings if self._visible_meeting(item)]
            report = detect_conflicts(
                meetings,
                ConflictPolicy(
                    include_tentative=self.config.include_tentative_conflicts,
                    include_all_day=self.config.include_all_day_conflicts,
                ),
            )
            conflict_ids = {item.uid for item in meetings if report.has_conflict(item.uid)}
        board.refresh(meetings, self.reminders, self.config, self._tz, conflict_ids)

    def _refresh_conflicts(self) -> None:
        panel = getattr(self, "_conflicts", None)
        if panel is None:
            return
        meetings: list[Meeting] = []
        report = detect_conflicts([])
        if self._snapshot is not None:
            meetings = [item for item in self._snapshot.meetings if self._visible_meeting(item)]
            report = detect_conflicts(meetings, self._conflict_policy())
        panel.show_report(meetings, report, self._tz)
        selected = getattr(self, "_selected_meeting", None)
        if selected is None:
            return
        current = next((item for item in meetings if item.uid == selected.uid), None)
        if current is None:
            self._details.clear()
            self._selected_meeting = None
            return
        self._details.show_meeting(current, report, {item.uid: item for item in meetings}, self._tz)

    def _update_header(self) -> None:
        today = datetime.now(self._tz).date()
        self.date_label.setText(format_long_date(today))

    def _restore_account(self) -> None:
        profile = load_profile(self.config.account_key(), self.paths)
        if profile.get("email") and not self.config.email:
            self.config.email = profile["email"]
            self.config.username = profile.get("username", "")
            self.config.domain = profile.get("domain", "")
            self.config.ews_url = profile.get("ews_url", "")
            if profile.get("auth_method"):
                self.config.auth_method = profile["auth_method"]
            self.config.normalized()
        self._password = load_password(self.config.account_key(), self.paths)

    def _persist_config(self) -> None:
        try:
            self.config.save(self.paths.config_file)
        except OSError:
            log.exception("Settings could not be saved.")

    def _on_auto_toggled(self, enabled: bool) -> None:
        self.config.auto_refresh = bool(enabled)
        self._persist_config()
        self.messages.set_auto(self.config.auto_refresh)
        if self._auto_action is not None:
            self._auto_action.blockSignals(True)
            self._auto_action.setChecked(self.config.auto_refresh)
            self._auto_action.blockSignals(False)
        self.refresh_service.apply_timer(self.config.auto_refresh, self.config.refresh_interval_minutes)
        self._render_status()
        self.messages.set_status(
            self._snapshot,
            self.refresh_service.next_refresh_at(),
            self.config,
            self._busy,
            self._tz,
        )

    def _on_interval_changed(self, minutes: int) -> None:
        self.config.refresh_interval_minutes = 10 if int(minutes) == 10 else 5
        self._persist_config()
        self.refresh_service.apply_timer(self.config.auto_refresh, self.config.refresh_interval_minutes)
        self._render_status()

    def open_settings(self) -> None:
        previous_view = self.config.default_view
        dialog = SettingsDialog(self.config, self._password, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.config = dialog.result_config
        account = self.config.account_key()
        if dialog.clear_password and not dialog.password_entered:
            delete_password(account, self.paths)
            self._password = ""
        else:
            if dialog.password_entered:
                self._password = dialog.result_password
                register_secret(self._password)
            stored, warning = save_credentials(
                account,
                self._password,
                {
                    "email": self.config.email,
                    "username": self.config.username,
                    "domain": self.config.domain,
                    "ews_url": self.config.ews_url,
                    "auth_method": self.config.auth_method,
                },
                self.paths,
            )
            if dialog.password_entered and not stored and warning:
                QMessageBox.warning(self, "Password storage", warning)
            elif stored:
                self.statusBar().showMessage("Account saved and encrypted on this computer.", 6000)
        self._persist_config()
        try:
            set_launch_at_login(self.config.launch_at_login)
        except OSError:
            QMessageBox.warning(self, "Settings", "The login item could not be updated.")
        self._tz = resolve_timezone(self.config.timezone)
        if hasattr(self, "todo_board"):
            self.todo_board.set_default_time(self.config.default_task_reminder_time)
            self.todo_board.set_today(datetime.now(self._tz).date())
        self.calendar.apply_preferences(
            self.config.week_starts_on,
            self.config.default_view if self.config.default_view != previous_view else None,
            self._tz,
            self.config.highlight_conflicts,
        )
        self.messages.set_auto(self.config.auto_refresh)
        self.messages.set_interval(self.config.refresh_interval_minutes)
        if self._auto_action is not None:
            self._auto_action.blockSignals(True)
            self._auto_action.setChecked(self.config.auto_refresh)
            self._auto_action.blockSignals(False)
        self._apply_visual_theme()
        self._sync_tray()
        self.refresh_service.apply_timer(self.config.auto_refresh, self.config.refresh_interval_minutes)
        self.refresh_service.refresh_now()

    def _open_meeting(self, meeting: Meeting) -> None:
        self._selected_meeting = meeting
        self._fill_details(meeting)
        self.calendar.focus_meeting(meeting)
        self._open_context("details")

    def _fill_details(self, meeting: Meeting) -> None:
        displayed = []
        if self._snapshot is not None:
            displayed = [item for item in self._snapshot.meetings if self._visible_meeting(item)]
        report = detect_conflicts(displayed, self._conflict_policy())
        by_id = {item.uid: item for item in displayed}
        self._details.show_meeting(meeting, report, by_id, self._tz)
        self._conflicts.show_report(displayed, report, self._tz)

    def _open_full_details(self, meeting: Meeting) -> None:
        displayed = []
        if self._snapshot is not None:
            displayed = [item for item in self._snapshot.meetings if self._visible_meeting(item)]
        report = detect_conflicts(displayed, self._conflict_policy())
        dialog = MeetingDetailsDialog(meeting, report, {item.uid: item for item in displayed}, self._tz, self)
        dialog.exec()

    def _focus_conflict(self, meeting: Meeting) -> None:
        self._open_meeting(meeting)

    def _conflict_policy(self) -> ConflictPolicy:
        return ConflictPolicy(
            include_tentative=self.config.include_tentative_conflicts,
            include_all_day=self.config.include_all_day_conflicts,
        )

    def _reveal_task(self, uid: str = "") -> None:
        if isinstance(uid, bool):
            uid = ""
        self._open_context("tasks")
        if uid and hasattr(self, "todo_board"):
            self.todo_board.select(uid)

    def _open_context(self, mode: str) -> None:
        titles = {
            "tasks": "Tasks",
            "reminders": "Reminders",
            "details": "Event",
            "conflicts": "Conflicts",
            "sync": "Sync",
        }
        indexes = {"tasks": 0, "reminders": 1, "details": 2, "conflicts": 3, "sync": 4}
        if mode not in indexes:
            return
        self._context_mode = mode
        self._context_pages.setCurrentIndex(indexes[mode])
        self._status_header.set_title(titles[mode])
        if not self._connection_open:
            self._set_connection_open(True, animate=True, persist=True)

    def _minimize_on_close(self) -> bool:
        return bool(
            self.config.minimize_to_tray
            and self.tray is not None
            and QSystemTrayIcon.isSystemTrayAvailable()
        )

    def should_start_minimized(self) -> bool:
        return bool(self.config.start_minimized and self.tray is not None)

    def show_normal(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        handle = self.windowHandle()
        if handle is not None:
            handle.requestActivate()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Context:
            return
        self.show_normal()

    def quit_application(self) -> None:
        if self._force_quit:
            return
        self._force_quit = True
        # Tray mode turns off quit-on-last-window-closed, so close() alone leaves
        # the process running. On Linux the indicator is still dispatching this
        # click, and quitting inside that callback is ignored. Finish next turn.
        QTimer.singleShot(0, self._finish_quit)

    def _finish_quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)
        self._remove_tray()
        self.close()
        if app is not None:
            app.quit()

    def changeEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._minimize_on_close()
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        if not self._force_quit and self._minimize_on_close():
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.notifications.show_message(
                    "Exchange Calendar is still running",
                    "The window was closed to the tray. Refresh continues in the background.",
                )
                self._tray_hint_shown = True
            return
        self._closing = True
        if self._connection_anim is not None:
            self._connection_anim.blockSignals(True)
            self._connection_anim.stop()
            self._connection_anim = None
        self._clock.stop()
        self._alarm_timer.stop()
        if self._alarm_popup is not None:
            self._alarm_popup.close()
        self.refresh_service.shutdown()
        self._remove_tray()
        event.accept()

    def _build_connection_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("columnHeader")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QHBoxLayout(rail)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addStretch(1)
        strip = QWidget()
        strip.setFixedWidth(_COLLAPSED_CONNECTION_WIDTH)
        column = QVBoxLayout(strip)
        column.setContentsMargins(0, 8, 0, 8)
        column.setSpacing(8)
        self._rail_toggle = make_button("", "icon")
        self._rail_toggle.setToolTip("Show connection")
        self._rail_toggle.clicked.connect(self._toggle_connection)
        self._rail_icon = QLabel()
        self._rail_icon.setFixedSize(16, 16)
        self._rail_icon.setToolTip("Show connection")
        column.addWidget(self._rail_toggle, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._rail_tasks = self._rail_mode_button(column, "Tasks", "tasks")
        self._rail_reminders = self._rail_mode_button(column, "Reminders", "reminders")
        self._rail_conflicts = self._rail_mode_button(column, "Scheduling conflicts", "conflicts")
        self._rail_sync = self._rail_mode_button(column, "Sync", "sync")
        column.addWidget(self._rail_icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        outer.addWidget(strip)
        return rail

    def _rail_mode_button(self, column: QVBoxLayout, tip: str, mode: str):
        button = make_button("", "icon")
        button.setToolTip(tip)
        button.clicked.connect(lambda _checked=False, chosen=mode: self._on_rail_mode(chosen))
        column.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        return button

    def _on_rail_mode(self, mode: str) -> None:
        if self._connection_open and self._context_mode == mode:
            self._toggle_connection()
            return
        self._open_context(mode)

    def _style_connection_drawer(self) -> None:
        if not hasattr(self, "_rail_toggle"):
            return
        palette = colors()
        muted = palette["muted"]
        accent = palette["accent"]
        toggle = self._status_header.toggle_button
        if toggle is not None:
            toggle.setIcon(chevron_icon("right", 14, muted))
        self._rail_toggle.setIcon(chevron_icon("left", 14, muted))
        self._rail_icon.setPixmap(messages_icon(16, accent).pixmap(16, 16))
        if hasattr(self, "_rail_tasks"):
            self._rail_tasks.setIcon(tasks_icon(16, muted))
            self._rail_reminders.setIcon(bell_icon(16, muted))
            self._rail_conflicts.setIcon(messages_icon(16, palette["danger"]))
            self._rail_sync.setIcon(refresh_icon(16, muted))

    def _toggle_connection(self) -> None:
        self._set_connection_open(not self._connection_open, animate=True, persist=True)

    def _set_connection_open(self, open_: bool, *, animate: bool, persist: bool) -> None:
        if self._connection_anim is not None:
            self._connection_anim.blockSignals(True)
            self._connection_anim.stop()
            self._connection_anim = None
            self._connection_animating = False
        self._connection_open = open_
        self._status_pane.setMinimumWidth(_COLLAPSED_CONNECTION_WIDTH)
        self._status_pane.setMaximumWidth(16777215)
        if not open_:
            self._remember_connection_width()
            self._connection_stack.setCurrentIndex(1)
        target = self._connection_width if open_ else _COLLAPSED_CONNECTION_WIDTH
        if open_:
            target = max(target, 280)
        self._animate_connection(target, animate=animate, opening=open_)
        if persist:
            self.config.connection_open = open_
            self._persist_config()

    def _remember_connection_width(self) -> None:
        sizes = self.splitter.sizes()
        if len(sizes) == 2 and sizes[1] >= 200:
            self._connection_width = sizes[1]

    def _animate_connection(self, target: int, *, animate: bool, opening: bool) -> None:
        sizes = self.splitter.sizes()
        start = sizes[1] if len(sizes) == 2 and sum(sizes) > 0 else target
        if not animate or abs(start - target) < 2:
            self._finish_connection(opening, target)
            return
        self._connection_animating = True
        animation = QVariantAnimation(self)
        animation.setStartValue(float(start))
        animation.setEndValue(float(target))
        animation.setDuration(190)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(lambda value: self._apply_connection_width(int(value)))
        animation.finished.connect(lambda: self._finish_connection(opening, target))
        self._connection_anim = animation
        animation.start()

    def _apply_connection_width(self, width: int) -> None:
        total = self.splitter.width()
        if total <= width:
            total = width + 700
        self.splitter.setSizes([total - width, width])

    def _finish_connection(self, opening: bool, target: int) -> None:
        self._connection_animating = False
        self._connection_anim = None
        if self._closing:
            return
        self._apply_connection_width(target)
        if opening:
            self._connection_stack.setCurrentIndex(0)
            self._status_pane.setMinimumWidth(280)
            self._status_pane.setMaximumWidth(16777215)
            self._connection_width = target
        else:
            self._connection_stack.setCurrentIndex(1)
            self._status_pane.setMinimumWidth(_COLLAPSED_CONNECTION_WIDTH)
            self._status_pane.setMaximumWidth(_COLLAPSED_CONNECTION_WIDTH)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sizes_initialized:
            width = max(self.splitter.width(), 900)
            open_width = min(max(int(width * 0.22), 280), 320)
            self._connection_width = open_width
            if self._connection_open:
                self.splitter.setSizes([width - open_width, open_width])
            else:
                self.splitter.setSizes([width - _COLLAPSED_CONNECTION_WIDTH, _COLLAPSED_CONNECTION_WIDTH])
            self._sizes_initialized = True


def _notification_actions(alarm, snooze_minutes: int) -> list[tuple[str, str]]:
    actions: list[tuple[str, str]] = []
    if alarm.url.startswith("http://") or alarm.url.startswith("https://"):
        actions.append(("join", "Join Meeting"))
    if alarm.kind == "todo":
        actions.append(("done", "Mark as Done"))
        actions.append(("open", "Open Task"))
    elif alarm.kind == "meeting" and alarm.conflict_name:
        actions.append(("conflict", "View Conflict"))
    if alarm.kind != "summary":
        actions.append(("snooze", f"Snooze {snooze_minutes} Minutes"))
    actions.append(("dismiss", "Dismiss"))
    return actions


def _alarm_title(alarm) -> str:
    if alarm.kind == "todo":
        return "TODO Reminder"
    if alarm.kind == "summary":
        return "Today's tasks"
    if alarm.conflict_name:
        return "Meeting Reminder — Conflict Detected"
    return "Meeting Reminder"


def _alarm_body(alarm, tz, now) -> str:
    clock = alarm.event_at.astimezone(tz).strftime("%H:%M")
    if alarm.kind == "todo":
        return f"{alarm.title}. Priority {alarm.priority or 'normal'}. Scheduled {clock}."
    if alarm.kind == "summary":
        return alarm.location or alarm.title
    lead = "Starting now" if alarm.offset_minutes <= 0 else f"Starts in {alarm.offset_minutes} minutes"
    if alarm.snoozed:
        lead = "Snoozed reminder"
    text = f"{alarm.title}. {lead}. {clock}."
    if alarm.conflict_name:
        text += f" Conflicts with {alarm.conflict_name} ({alarm.conflict_minutes} minutes)."
    if alarm.cached:
        text += " From the saved calendar."
    return text
