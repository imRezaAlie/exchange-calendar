"""Settings for Exchange, calendar display, refresh, conflicts, and startup."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.calendar.date_utils import resolve_timezone
from app.config import AppConfig, AppPaths
from app.services.alarm_sound import play_alarm
from app.ui.colors import colors
from app.ui.widgets import make_button
from app.exchange.authentication import map_exception
from app.exchange.client import ExchangeClient

_TIMEZONES = (
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Istanbul",
    "Asia/Tehran",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Australia/Sydney",
)


class _ConnectionTest(QThread):
    result = Signal(bool, str)

    def __init__(self, config: AppConfig, password: str) -> None:
        super().__init__()
        self.config = config
        self.password = password

    def run(self) -> None:
        try:
            client = ExchangeClient(self.config, self.password)
            client.connect(resolve_timezone(self.config.timezone))
            self.result.emit(True, client.version_text())
        except Exception as exc:
            self.result.emit(False, str(map_exception(exc)))


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, password: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(860, 620)
        self.setMinimumSize(760, 520)
        self._original_password = password
        self._test_thread: _ConnectionTest | None = None
        self.result_config = config
        self.result_password = password
        self.password_entered = False
        self.clear_password = False
        self.view_changed = False
        self._initial_view = config.default_view

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        nav = QWidget()
        nav.setObjectName("settingsNav")
        nav.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav.setFixedWidth(220)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(12, 16, 12, 16)
        nav_layout.setSpacing(4)
        self._pages = QStackedWidget()
        pages = (
            ("Exchange Connection", self._exchange_tab(config)),
            ("Calendar", self._calendar_tab(config)),
            ("TODO Management", self._todo_tab(config)),
            ("Reminders && Alarms", self._reminders_tab(config)),
            ("Appearance", self._appearance_tab(config)),
            ("General", self._general_tab(config)),
        )
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (title, page) in enumerate(pages):
            button = QPushButton(title)
            button.setObjectName("navItem")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(36)
            group.addButton(button, index)
            nav_layout.addWidget(button)
            self._pages.addWidget(self._scroll(page))
        group.idClicked.connect(self._pages.setCurrentIndex)
        first = group.button(0)
        if first is not None:
            first.setChecked(True)
        nav_layout.addStretch(1)
        body.addWidget(nav)
        body.addWidget(self._pages, 1)
        root.addLayout(body, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(16, 12, 16, 16)
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel = make_button("Cancel", "secondary")
        save = make_button("Save", "primary")
        cancel.setFixedWidth(96)
        save.setFixedWidth(96)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)
        self._on_auth_changed()

    def _exchange_tab(self, config: AppConfig) -> QWidget:
        page, form = self._form_page()
        intro = QLabel(
            "Enter the account once. The password and connection are encrypted on this computer "
            "and loaded the next time you open the calendar."
        )
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        form.addRow(intro)
        self.email = QLineEdit(config.email)
        self.username = QLineEdit(config.username)
        self.username.setPlaceholderText("DOMAIN\\username")
        self.domain = QLineEdit(config.domain)
        self.ews_url = QLineEdit(config.ews_url)
        self.ews_url.setPlaceholderText("https://exchange.company.com/EWS/Exchange.asmx")
        self.auth_method = QComboBox()
        self.auth_method.addItem("NTLM", "ntlm")
        self.auth_method.addItem("Basic (HTTPS only)", "basic")
        self.auth_method.addItem("Kerberos", "kerberos")
        index = max(0, self.auth_method.findData(config.auth_method))
        self.auth_method.setCurrentIndex(index)
        self.auth_method.currentIndexChanged.connect(self._on_auth_changed)
        self.autodiscover = QCheckBox("Use Autodiscover")
        self.autodiscover.setChecked(config.use_autodiscover)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        if self._original_password:
            self.password.setPlaceholderText("Saved and encrypted — leave blank to keep it")
        else:
            self.password.setPlaceholderText("Encrypted on this computer after you save")
        self.show_password = QCheckBox("Show password")
        self.show_password.toggled.connect(
            lambda checked: self.password.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        clear = make_button("Clear saved password", "danger")
        clear.clicked.connect(self._clear_password)
        self.ca_bundle = QLineEdit(config.ca_bundle)
        browse = make_button("Browse…", "secondary")
        browse.setFixedWidth(96)
        browse.clicked.connect(self._browse_ca)
        ca_row = QHBoxLayout()
        ca_row.addWidget(self.ca_bundle, 1)
        ca_row.addWidget(browse)
        self.basic_hint = QLabel(
            "Basic authentication sends the password over HTTPS. Use it only when this Exchange server requires it."
        )
        self.basic_hint.setWordWrap(True)
        self.basic_hint.setObjectName("hintLabel")
        self.test_button = make_button("Test Connection", "secondary")
        self.test_button.clicked.connect(self._test_connection)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        form.addRow("Email", self.email)
        form.addRow("Username", self.username)
        form.addRow("Domain", self.domain)
        form.addRow("EWS URL", self.ews_url)
        form.addRow("Authentication", self.auth_method)
        form.addRow("", self.autodiscover)
        form.addRow("Password", self.password)
        form.addRow("", self.show_password)
        form.addRow("", clear)
        form.addRow("Corporate CA", ca_row)
        form.addRow("", self.basic_hint)
        form.addRow("", self.test_button)
        form.addRow("", self.test_result)
        return page

    def _calendar_tab(self, config: AppConfig) -> QWidget:
        page, form = self._form_page()
        self.default_view = QComboBox()
        self.default_view.addItem("Day", "daily")
        self.default_view.addItem("Week", "weekly")
        self.default_view.addItem("Month", "monthly")
        self.default_view.addItem("Agenda", "agenda")
        view_index = self.default_view.findData(config.default_view)
        self.default_view.setCurrentIndex(view_index if view_index >= 0 else 1)
        self.week_start = QComboBox()
        self.week_start.addItem("Monday", "monday")
        self.week_start.addItem("Sunday", "sunday")
        self.week_start.setCurrentIndex(0 if config.week_starts_on == "monday" else 1)
        self.timezone = QComboBox()
        self.timezone.setEditable(True)
        self.timezone.addItem("System default")
        for name in _TIMEZONES:
            self.timezone.addItem(name)
        current = config.timezone or "System default"
        if self.timezone.findText(current) < 0:
            self.timezone.addItem(current)
        self.timezone.setCurrentText(current)
        self.show_cancelled = QCheckBox("Show cancelled meetings")
        self.show_cancelled.setChecked(config.show_cancelled)
        self.show_all_day = QCheckBox("Show all-day events")
        self.show_all_day.setChecked(config.show_all_day)
        form.addRow("Default view", self.default_view)
        form.addRow("Week starts on", self.week_start)
        form.addRow("Timezone", self.timezone)
        form.addRow("", self.show_cancelled)
        form.addRow("", self.show_all_day)
        self.highlight = QCheckBox("Highlight conflicting meetings")
        self.highlight.setChecked(config.highlight_conflicts)
        self.include_tentative = QCheckBox("Include tentative meetings")
        self.include_tentative.setChecked(config.include_tentative_conflicts)
        self.include_all_day = QCheckBox("Include all-day events")
        self.include_all_day.setChecked(config.include_all_day_conflicts)
        note = QLabel(
            "Cancelled meetings, free entries, and declined responses are not treated as conflicts. "
            "A meeting that ends when the next one starts is not a conflict."
        )
        note.setWordWrap(True)
        note.setObjectName("hintLabel")
        form.addRow("", self.highlight)
        form.addRow("", self.include_tentative)
        form.addRow("", self.include_all_day)
        form.addRow(note)
        return page

    def _appearance_tab(self, config: AppConfig) -> QWidget:
        page, form = self._form_page()
        intro = QLabel("Light uses a light page. Dark keeps the same layout on a black surface.")
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.setCurrentIndex(1 if config.theme == "dark" else 0)
        form.addRow(intro)
        form.addRow("Theme", self.theme)
        return page

    def _general_tab(self, config: AppConfig) -> QWidget:
        page, form = self._form_page()
        intro = QLabel("Startup, the system tray, and how often the calendar refreshes.")
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        self.start_minimized = QCheckBox("Start minimized")
        self.start_minimized.setChecked(config.start_minimized)
        self.minimize_to_tray = QCheckBox("Keep running in the tray when the window is closed")
        self.minimize_to_tray.setChecked(config.minimize_to_tray)
        self.minimize_to_tray.setToolTip(
            "Leave the calendar in the top bar. Open Calendar brings the window back, and Exit quits it."
        )
        self.launch_at_login = QCheckBox("Launch at login")
        self.launch_at_login.setChecked(config.launch_at_login)
        self.auto_refresh = QCheckBox("Refresh automatically")
        self.auto_refresh.setChecked(config.auto_refresh)
        self.interval = QComboBox()
        self.interval.addItem("5 minutes", 5)
        self.interval.addItem("10 minutes", 10)
        self.interval.setCurrentIndex(0 if config.refresh_interval_minutes != 10 else 1)
        form.addRow(intro)
        form.addRow("", self.start_minimized)
        form.addRow("", self.minimize_to_tray)
        form.addRow("", self.launch_at_login)
        form.addRow("", self.auto_refresh)
        form.addRow("Refresh interval", self.interval)
        return page

    def _form_page(self) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(24, 16, 24, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return page, form

    def _scroll(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _on_auth_changed(self) -> None:
        basic = self.auth_method.currentData() == "basic"
        self.basic_hint.setVisible(basic)

    def _clear_password(self) -> None:
        self.clear_password = True
        self.password.clear()
        self.test_result.setText("The saved password will be removed when you click OK.")

    def _browse_ca(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Corporate CA bundle",
            "",
            "Certificates (*.pem *.crt *.cer);;All files (*)",
        )
        if path:
            self.ca_bundle.setText(path)

    def _reminders_tab(self, config: AppConfig) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(24, 16, 24, 16)
        form.setSpacing(8)
        intro = QLabel("Bells, desktop notifications, and how early a meeting should ring.")
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        form.addWidget(intro)
        self.reminders_enabled = QCheckBox("Enable all reminders")
        self.reminders_enabled.setChecked(config.reminders_enabled)
        self.alarm_sound_enabled = QCheckBox("Play the bell")
        self.alarm_sound_enabled.setChecked(config.alarm_sound_enabled)
        self.desktop_notifications = QCheckBox("Desktop notifications")
        self.desktop_notifications.setChecked(config.desktop_notifications_enabled)
        self.alarm_popup_enabled = QCheckBox("Alarm popup")
        self.alarm_popup_enabled.setChecked(config.alarm_popup_enabled)
        self.alarms_muted = QCheckBox("Mute alarms (visual reminders stay on)")
        self.alarms_muted.setChecked(config.alarms_muted)
        for box in (
            self.reminders_enabled,
            self.alarm_sound_enabled,
            self.desktop_notifications,
            self.alarm_popup_enabled,
            self.alarms_muted,
        ):
            form.addWidget(box)

        sound_row = QHBoxLayout()
        self.alarm_sound = QComboBox()
        self.alarm_sound.addItem("Classic Bell", "classic")
        self.alarm_sound.addItem("Soft Bell", "soft")
        self.alarm_sound.addItem("Digital Chime", "digital")
        self.alarm_sound.addItem("Alert Tone", "alert")
        sound_index = self.alarm_sound.findData(config.alarm_sound)
        self.alarm_sound.setCurrentIndex(sound_index if sound_index >= 0 else 0)
        self.alarm_volume = QSpinBox()
        self.alarm_volume.setRange(0, 100)
        self.alarm_volume.setSuffix("%")
        self.alarm_volume.setValue(int(config.alarm_volume))
        test = make_button("Test Alarm", "secondary")
        test.setFixedWidth(120)
        test.clicked.connect(self._test_alarm)
        sound_row.addWidget(self.alarm_sound, 1)
        sound_row.addWidget(self.alarm_volume)
        sound_row.addWidget(test)
        form.addLayout(sound_row)

        meeting_label = QLabel("Meeting reminders")
        meeting_label.setObjectName("panelHeading")
        form.addWidget(meeting_label)
        self.meeting_reminders_enabled = QCheckBox("Enable meeting reminders")
        self.meeting_reminders_enabled.setChecked(config.meeting_reminders_enabled)
        form.addWidget(self.meeting_reminders_enabled)
        offsets = set(config.meeting_reminder_offsets or [])
        self.offset_boxes = []
        for minutes, label in ((30, "30 minutes before"), (15, "15 minutes before"), (10, "10 minutes before"), (5, "5 minutes before"), (0, "At the meeting start")):
            box = QCheckBox(label)
            box.setChecked(minutes in offsets)
            box.setProperty("offset", minutes)
            self.offset_boxes.append(box)
            form.addWidget(box)
        self.conflict_alarm_warnings = QCheckBox("Warn when the meeting conflicts with another")
        self.conflict_alarm_warnings.setChecked(config.conflict_alarm_warnings)
        self.respect_exchange_reminder = QCheckBox("Use the Exchange reminder time when the meeting has one")
        self.respect_exchange_reminder.setChecked(config.respect_exchange_reminder)
        form.addWidget(self.conflict_alarm_warnings)
        form.addWidget(self.respect_exchange_reminder)
        self.join_reminder = QComboBox()
        self.join_reminder.addItem("Off", 0)
        self.join_reminder.addItem("2 minutes before", 2)
        self.join_reminder.addItem("5 minutes before", 5)
        self.join_reminder.addItem("10 minutes before", 10)
        reminder_index = self.join_reminder.findData(config.join_reminder_minutes)
        self.join_reminder.setCurrentIndex(reminder_index if reminder_index >= 0 else 2)
        join_row = QHBoxLayout()
        join_row.addWidget(QLabel("Join reminder"))
        join_row.addWidget(self.join_reminder, 1)
        form.addLayout(join_row)

        snooze_label = QLabel("Snooze")
        snooze_label.setObjectName("panelHeading")
        form.addWidget(snooze_label)
        self.snooze_enabled = QCheckBox("Allow snooze")
        self.snooze_enabled.setChecked(config.snooze_enabled)
        form.addWidget(self.snooze_enabled)
        snooze_row = QHBoxLayout()
        self.default_snooze = QComboBox()
        for minutes in (5, 10, 15, 30):
            self.default_snooze.addItem(f"{minutes} minutes", minutes)
        snooze_index = self.default_snooze.findData(config.default_snooze_minutes)
        self.default_snooze.setCurrentIndex(snooze_index if snooze_index >= 0 else 0)
        self.max_repeats = QSpinBox()
        self.max_repeats.setRange(1, 4)
        self.max_repeats.setValue(int(config.max_repeated_reminders))
        snooze_row.addWidget(QLabel("Default snooze"))
        snooze_row.addWidget(self.default_snooze)
        snooze_row.addWidget(QLabel("Repeat important bells"))
        snooze_row.addWidget(self.max_repeats)
        form.addLayout(snooze_row)
        form.addStretch(1)
        return page

    def _todo_tab(self, config: AppConfig) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(24, 16, 24, 16)
        form.setSpacing(8)
        intro = QLabel("Unfinished tasks can move to the next day. Reminders use the time you set on each task.")
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        form.addWidget(intro)
        self.todo_reminders_enabled = QCheckBox("Enable task reminders")
        self.todo_reminders_enabled.setChecked(config.todo_reminders_enabled)
        self.overdue_reminders = QCheckBox("Remind once for a task whose time already passed today")
        self.overdue_reminders.setChecked(config.overdue_reminders_enabled)
        self.carry_forward_reminders = QCheckBox("Keep reminders when unfinished tasks move to the next day")
        self.carry_forward_reminders.setChecked(config.carry_forward_reminders)
        self.daily_todo_summary = QCheckBox("Morning summary of today's tasks")
        self.daily_todo_summary.setChecked(config.daily_todo_summary)
        for box in (
            self.todo_reminders_enabled,
            self.overdue_reminders,
            self.carry_forward_reminders,
            self.daily_todo_summary,
        ):
            form.addWidget(box)
        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        time_row.addWidget(QLabel("Default reminder time"))
        self.default_task_time = QLineEdit(config.default_task_reminder_time)
        self.default_task_time.setPlaceholderText("09:00")
        self.default_task_time.setFixedWidth(96)
        time_row.addWidget(self.default_task_time)
        time_row.addStretch(1)
        form.addLayout(time_row)
        form.addStretch(1)
        return page

    def _selected_offsets(self) -> list[int]:
        return [int(box.property("offset")) for box in self.offset_boxes if box.isChecked()]

    def _test_alarm(self) -> None:
        play_alarm(
            AppPaths().data_dir / "sounds",
            str(self.alarm_sound.currentData()),
            int(self.alarm_volume.value()),
            1,
        )

    def _collect(self) -> AppConfig:
        timezone_name = self.timezone.currentText().strip()
        if timezone_name.lower() in {"", "system default", "local", "system"}:
            timezone_name = ""
        else:
            try:
                ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"Unknown timezone: {timezone_name}") from exc
        url = self.ews_url.text().strip()
        if url and not url.lower().startswith("https://"):
            raise ValueError("The EWS URL must start with https://. Certificate verification cannot be disabled.")
        if self.auth_method.currentData() == "basic" and url and not url.lower().startswith("https://"):
            raise ValueError("Basic authentication is available only over HTTPS.")
        config = AppConfig(
            email=self.email.text().strip(),
            username=self.username.text().strip(),
            domain=self.domain.text().strip(),
            ews_url=url,
            auth_method=str(self.auth_method.currentData()),
            use_autodiscover=self.autodiscover.isChecked(),
            timezone=timezone_name,
            default_view=str(self.default_view.currentData()),
            week_starts_on=str(self.week_start.currentData()),
            show_cancelled=self.show_cancelled.isChecked(),
            show_all_day=self.show_all_day.isChecked(),
            auto_refresh=self.auto_refresh.isChecked(),
            refresh_interval_minutes=int(self.interval.currentData()),
            highlight_conflicts=self.highlight.isChecked(),
            include_tentative_conflicts=self.include_tentative.isChecked(),
            include_all_day_conflicts=self.include_all_day.isChecked(),
            start_minimized=self.start_minimized.isChecked(),
            minimize_to_tray=self.minimize_to_tray.isChecked(),
            launch_at_login=self.launch_at_login.isChecked(),
            join_reminder_minutes=int(self.join_reminder.currentData()),
            meeting_reminder_offsets=self._selected_offsets(),
            reminders_enabled=self.reminders_enabled.isChecked(),
            alarm_sound_enabled=self.alarm_sound_enabled.isChecked(),
            desktop_notifications_enabled=self.desktop_notifications.isChecked(),
            alarm_popup_enabled=self.alarm_popup_enabled.isChecked(),
            alarm_volume=int(self.alarm_volume.value()),
            alarm_sound=str(self.alarm_sound.currentData()),
            alarms_muted=self.alarms_muted.isChecked(),
            meeting_reminders_enabled=self.meeting_reminders_enabled.isChecked(),
            conflict_alarm_warnings=self.conflict_alarm_warnings.isChecked(),
            respect_exchange_reminder=self.respect_exchange_reminder.isChecked(),
            todo_reminders_enabled=self.todo_reminders_enabled.isChecked(),
            default_task_reminder_time=self.default_task_time.text().strip() or "09:00",
            overdue_reminders_enabled=self.overdue_reminders.isChecked(),
            carry_forward_reminders=self.carry_forward_reminders.isChecked(),
            daily_todo_summary=self.daily_todo_summary.isChecked(),
            snooze_enabled=self.snooze_enabled.isChecked(),
            default_snooze_minutes=int(self.default_snooze.currentData()),
            max_repeated_reminders=int(self.max_repeats.value()),
            connection_open=self.result_config.connection_open,
            theme=str(self.theme.currentData() or "light"),
            ca_bundle=self.ca_bundle.text().strip(),
            cache_retention_days=self.result_config.cache_retention_days,
        )
        return config.normalized()

    def _password_for_test(self) -> str:
        entered = self.password.text()
        if entered:
            return entered
        if self.clear_password:
            return ""
        return self._original_password

    def _test_connection(self) -> None:
        try:
            config = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Settings", str(exc))
            return
        password = self._password_for_test()
        if config.auth_method != "kerberos" and not password:
            QMessageBox.warning(self, "Settings", "Enter the Exchange password before testing the connection.")
            return
        if not config.email:
            QMessageBox.warning(self, "Settings", "Enter the Exchange email address.")
            return
        self.test_button.setEnabled(False)
        self.test_result.setText("Testing connection…")
        self._test_thread = _ConnectionTest(config, password)
        self._test_thread.result.connect(self._on_test_result)
        self._test_thread.start()

    def _on_test_result(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        color = colors()["connected"] if ok else colors()["danger"]
        self.test_result.setStyleSheet(f"color: {color};")
        self.test_result.setText(message)

    def accept(self) -> None:
        try:
            config = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Settings", str(exc))
            return
        entered = self.password.text()
        self.result_config = config
        self.view_changed = config.default_view != self._initial_view
        if self.clear_password and not entered:
            self.result_password = ""
            self.password_entered = False
        elif entered:
            self.result_password = entered
            self.password_entered = True
            self.clear_password = False
        else:
            self.result_password = self._original_password
            self.password_entered = False
        super().accept()

    def reject(self) -> None:
        thread = self._test_thread
        if thread is not None and thread.isRunning():
            thread.wait(1500)
        super().reject()
