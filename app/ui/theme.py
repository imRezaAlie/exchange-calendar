"""Apply the light paper page or the Dracula dark page on GNOME and KDE."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from app.ui.colors import use_colors

FONT_FAMILIES = (
    "Ubuntu Sans Mono",
    "Ubuntu Mono",
    "Noto Sans Mono",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Noto Mono",
)
FONT_CSS = ", ".join(f'"{name}"' for name in FONT_FAMILIES) + ", monospace"


def apply_theme(app: QApplication, name: str = "light") -> None:
    palette_colors = use_colors(name)
    app.setStyle("Fusion")
    palette = QPalette()
    page = QColor(palette_colors["page"])
    text = QColor(palette_colors["text"])
    palette.setColor(QPalette.ColorRole.Window, page)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor(palette_colors["input"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(palette_colors["column"]))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor(palette_colors["button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(palette_colors["accent_soft"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, text)
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette_colors["tooltip_bg"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(palette_colors["tooltip_text"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(palette_colors["accent"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(palette_colors["muted"]))
    palette.setColor(QPalette.ColorRole.Mid, QColor(palette_colors["button_line"]))
    app.setPalette(palette)
    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(13)
    app.setFont(font)
    stylesheet = Path(__file__).with_name("styles.qss").read_text(encoding="utf-8")
    stylesheet = stylesheet.replace("@font@", FONT_CSS)
    for key, value in palette_colors.items():
        stylesheet = stylesheet.replace(f"@{key}@", value)
    app.setStyleSheet(stylesheet)
