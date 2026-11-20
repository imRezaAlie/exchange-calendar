"""Connection and refresh column."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.models import SyncSnapshot
from app.ui.colors import colors
from app.ui.icons import dot_pixmap, refresh_icon
from app.ui.widgets import make_button


class MessagesPanel(QWidget):
    auto_refresh_changed = Signal(bool)
    interval_changed = Signal(int)
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        headline = QHBoxLayout()
        headline.setSpacing(8)
        self.status_dot = QLabel()
        self.status_dot.setPixmap(dot_pixmap(10, colors()["starting"]))
        self.status_dot.setFixedSize(10, 10)
        self.exchange_value = QLabel("Starting")
        self.exchange_value.setObjectName("statusHeadline")
        self.exchange_value.setWordWrap(True)
        headline.addWidget(self.status_dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        headline.addWidget(self.exchange_value, 1)
        root.addLayout(headline)

        self.status_detail = QLabel("Preparing the calendar…")
        self.status_detail.setObjectName("statusDetail")
        self.status_detail.setWordWrap(True)
        root.addWidget(self.status_detail)

        facts = QFrame()
        facts.setObjectName("statusCard")
        facts.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QVBoxLayout(facts)
        form.setContentsMargins(16, 12, 16, 12)
        form.setSpacing(8)
        self.account_value = self._add_row(form, "Account")
        self.last_sync_value = self._add_row(form, "Last sync")
        self.next_refresh_value = self._add_row(form, "Next refresh")
        self.data_value = self._add_row(form, "Calendar")
        self.auto_value = self._add_row(form, "Auto refresh")
        root.addWidget(facts)

        self.error_label = QLabel("")
        self.error_label.setObjectName("errorBanner")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        refresh_title = QLabel("Refresh")
        refresh_title.setObjectName("panelHeading")
        root.addWidget(refresh_title)

        self.auto_box = QCheckBox("Refresh automatically")
        self.auto_box.setToolTip("Keep the calendar up to date while the application is open")
        self.auto_box.toggled.connect(self.auto_refresh_changed.emit)
        root.addWidget(self.auto_box)

        interval_row = QHBoxLayout()
        interval_row.setSpacing(8)
        interval_label = QLabel("Every")
        self.interval_combo = QComboBox()
        self.interval_combo.addItem("5 minutes", 5)
        self.interval_combo.addItem("10 minutes", 10)
        self.interval_combo.setToolTip("How often the calendar is refreshed")
        self.interval_combo.currentIndexChanged.connect(self._emit_interval)
        interval_row.addWidget(interval_label)
        interval_row.addWidget(self.interval_combo, 1)
        root.addLayout(interval_row)

        self.refresh_button = make_button("Refresh now", "primary", refresh_icon(16, colors()["primary_text"]))
        self.refresh_button.setToolTip("Refresh immediately (F5)")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        root.addWidget(self.refresh_button)

        hint = QLabel("Select a meeting to open its details.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)

    def _add_row(self, layout: QVBoxLayout, label: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel(label)
        name.setObjectName("factLabel")
        name.setMinimumWidth(92)
        value = QLabel("—")
        value.setObjectName("factValue")
        value.setWordWrap(False)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(name)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    def _show_account(self, value: str) -> None:
        text = (value or "").strip() or "—"
        self.account_value.setText(text)
        self.account_value.setToolTip("" if text == "—" else text)

    def _emit_interval(self) -> None:
        self.interval_changed.emit(int(self.interval_combo.currentData()))

    def set_auto(self, enabled: bool) -> None:
        self.auto_box.blockSignals(True)
        self.auto_box.setChecked(enabled)
        self.auto_box.blockSignals(False)

    def set_interval(self, minutes: int) -> None:
        self.interval_combo.blockSignals(True)
        self.interval_combo.setCurrentIndex(0 if int(minutes) != 10 else 1)
        self.interval_combo.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.refresh_button.setText("Refreshing…" if busy else "Refresh now")
        tint = colors()["disabled_text"] if busy else colors()["primary_text"]
        self.refresh_button.setIcon(refresh_icon(15, tint))

    def set_status(
        self,
        snapshot: SyncSnapshot | None,
        next_refresh: datetime | None,
        config: AppConfig,
        busy: bool,
        tz: ZoneInfo,
    ) -> None:
        self.set_busy(busy)
        self.auto_value.setText("On" if config.auto_refresh else "Off")
        self.next_refresh_value.setText(
            next_refresh.astimezone(tz).strftime("%H:%M") if next_refresh else "Off"
        )
        palette = colors()
        if snapshot is None:
            self._apply_state("Starting", palette["starting"], "Preparing the calendar…", "—", "")
            self._show_account(config.email)
            self.last_sync_value.setText("—")
            return
        if snapshot.demo:
            self._apply_state(
                "Demo mode",
                palette["demo"],
                "Sample meetings, including overlaps. No Exchange account is required.",
                "Sample calendar",
                "",
            )
        elif snapshot.connected and not snapshot.from_cache:
            self._apply_state(
                "Connected",
                palette["connected"],
                "The calendar is up to date.",
                "Live calendar",
                snapshot.error or "",
            )
        elif snapshot.from_cache:
            self._apply_state(
                "Showing saved calendar",
                palette["warning"],
                "Exchange is unavailable. The last successful calendar stays on screen.",
                "Saved calendar",
                snapshot.error or "",
            )
        else:
            self._apply_state(
                "Not connected",
                palette["danger"],
                "Open Settings and enter the Exchange connection.",
                "—",
                snapshot.error or "",
            )
        self._show_account(snapshot.mailbox or config.email)
        if snapshot.synced_at is None:
            self.last_sync_value.setText("—")
        else:
            stamp = snapshot.synced_at.astimezone(tz).strftime("%H:%M")
            self.last_sync_value.setText(f"{stamp}, saved" if snapshot.from_cache else stamp)

    def _apply_state(self, headline: str, color: str, detail: str, source: str, error: str) -> None:
        self.exchange_value.setText(headline)
        self.exchange_value.setStyleSheet(f"color: {color}; background: transparent;")
        self.status_dot.setPixmap(dot_pixmap(10, color))
        self.status_detail.setText(detail)
        self.data_value.setText(source)
        self.error_label.setText(error)
        self.error_label.setVisible(bool(error))
