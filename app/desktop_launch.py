"""Install the Ubuntu launcher so the application can be pinned to the dock."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ID = "exchange-calendar"
_SIZES = (16, 24, 32, 48, 64, 128, 256)
_DESKTOP_RESERVED = set(' \t\n"\'\\><~|&;$*?#()`')
INSTALLED_ROOT = Path.home() / ".local" / "lib" / "exchange-calendar"


def install_launcher(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[1]
    if project_root is None and root.resolve() != INSTALLED_ROOT.resolve() and (INSTALLED_ROOT / "main.py").is_file():
        root = INSTALLED_ROOT
    command = install_command(root)
    _install_icons()
    desktop_dir = Path.home() / ".local" / "share" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop = desktop_dir / f"{APP_ID}.desktop"
    desktop.write_text(
        "\n".join(
            (
                "[Desktop Entry]",
                "Version=1.0",
                "Type=Application",
                "Name=Exchange Calendar",
                "GenericName=Calendar",
                "Comment=Exchange calendar for developers",
                f"Exec={_desktop_quote(str(command))}",
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


def install_application(source: Path | None = None) -> Path:
    """Copy the app to a fixed folder and point the menu icon at that copy."""
    origin = source or Path(__file__).resolve().parents[1]
    _sync_sources(origin, INSTALLED_ROOT)
    _ensure_venv(INSTALLED_ROOT)
    return install_launcher(INSTALLED_ROOT)


def _sync_sources(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("main.py", "requirements.txt", "config.example.json"):
        shutil.copy2(source / name, dest / name)
    app_dest = dest / "app"
    if app_dest.exists():
        shutil.rmtree(app_dest)
    shutil.copytree(source / "app", app_dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _ensure_venv(root: Path) -> None:
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        subprocess.check_call([sys.executable, "-m", "venv", str(root / ".venv")])
    subprocess.check_call([str(python), "-m", "pip", "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL)
    subprocess.check_call(
        [str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")],
        stdout=subprocess.DEVNULL,
    )


def install_command(project_root: Path | None = None, destination: Path | None = None) -> Path:
    """Write a command that starts the app without activating the virtual environment."""
    root = project_root or Path(__file__).resolve().parents[1]
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        python = Path(sys.executable)
    script = destination or (Path.home() / ".local" / "bin" / APP_ID)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"exec {_shell_quote(python)} {_shell_quote(root / 'main.py')} \"$@\"\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    return script


def _shell_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "'\\''") + "'"


def _desktop_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    if any(character in value for character in _DESKTOP_RESERVED):
        return f'"{escaped}"'
    return escaped


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
