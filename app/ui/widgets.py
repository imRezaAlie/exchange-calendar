"""Shared controls. Every button in the application is created here."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

BUTTON_HEIGHT = 36
BUTTON_RADIUS = 6
ICON_SIZE = 16

_OBJECT_NAMES = {
    "primary": "btnPrimary",
    "secondary": "btnSecondary",
    "danger": "btnDanger",
    "icon": "btnIcon",
    "toggle": "btnToggle",
}


def restyle(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def make_button(text: str = "", variant: str = "secondary", icon: QIcon | None = None) -> QPushButton:
    """Standard 36px button. Icon buttons are 36×36."""
    button = QPushButton(text)
    button.setObjectName(_OBJECT_NAMES[variant])
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    button.setProperty("variant", variant)
    if variant == "icon":
        button.setFixedSize(BUTTON_HEIGHT, BUTTON_HEIGHT)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    else:
        button.setFixedHeight(BUTTON_HEIGHT)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    if icon is not None:
        button.setIcon(icon)
    return button


class SectionHeader(QWidget):
    """One section title, 48px tall, with optional trailing controls."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("columnHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("sectionTitle")
        layout.addWidget(self.title, 1)
        self._trailing = QHBoxLayout()
        self._trailing.setContentsMargins(0, 0, 0, 0)
        self._trailing.setSpacing(8)
        layout.addLayout(self._trailing)

    def add_trailing(self, widget: QWidget) -> None:
        self._trailing.addWidget(widget)
