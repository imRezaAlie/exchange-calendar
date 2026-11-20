"""Install the Ubuntu launcher so the application can be pinned to the dock."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "exchange-calendar"
_SIZES = (16, 24, 32, 48, 64, 128, 256)


def install_launcher(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        python = Path(sys.executable)
    main = root / "main.py"
    _install_icons()
    desktop_dir = Path.home() / ".local" / "share" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop = desktop_dir / f"{APP_ID}.desktop"
    command = f"{python} {main}"
    desktop.write_text(
        "\n".join(
            (
                "[Desktop Entry]",
                "Version=1.0",
                "Type=Application",
                "Name=Exchange Calendar",
                "GenericName=Calendar",
                "Comment=Exchange calendar for developers",
                f"Exec={command}",
                f"Icon={APP_ID}",
                "Terminal=false",
                "Categories=Office;Calendar;",
                f"StartupWMClass={APP_ID}",
                "StartupNotify=true",
                "",
            )
        ),
        encoding="utf-8",
    )
    os.chmod(desktop, 0o644)
    return desktop


def _install_icons() -> None:
    from PySide6.QtWidgets import QApplication

    from app.ui.icons import app_mark

    if QApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QApplication([])
    icon_root = Path.home() / ".local" / "share" / "icons" / "hicolor"
    for size in _SIZES:
        folder = icon_root / f"{size}x{size}" / "apps"
        folder.mkdir(parents=True, exist_ok=True)
        app_mark(size).save(str(folder / f"{APP_ID}.png"), "PNG")
