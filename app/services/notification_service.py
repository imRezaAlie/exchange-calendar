"""Tray notifications for sync failures and recovery. Silent when no tray exists."""

from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon


class NotificationService:
    def __init__(self, tray: QSystemTrayIcon | None) -> None:
        self._tray = tray
        self._last: tuple[str, str] | None = None

    def sync_failed(self, message: str) -> None:
        self._notify("Exchange calendar sync failed", message, QSystemTrayIcon.MessageIcon.Warning)

    def sync_recovered(self) -> None:
        self._notify(
            "Exchange calendar connected",
            "Calendar synchronization succeeded.",
            QSystemTrayIcon.MessageIcon.Information,
        )

    def show_message(self, title: str, message: str) -> None:
        self._notify(title, message, QSystemTrayIcon.MessageIcon.Information)

    def _notify(self, title: str, message: str, icon: QSystemTrayIcon.MessageIcon) -> None:
        if self._tray is None or not QSystemTrayIcon.supportsMessages():
            return
        text = " ".join(message.split())[:240]
        key = (title, text)
        if key == self._last:
            return
        self._last = key
        self._tray.showMessage(title, text, icon, 4000)
