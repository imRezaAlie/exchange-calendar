#!/usr/bin/env python3
"""Outlook Today style calendar for an on-premises Exchange server."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.config import AppPaths, load_config
from app.logging_config import setup_logging
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Outlook Today style Exchange calendar for Ubuntu.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Show sample meetings and conflicts without connecting to Exchange.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level, for example INFO or DEBUG.")
    return parser


_INSTANCE_NAME = "exchange-calendar"


def _process_state(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("State:"):
            parts = line.split()
            return parts[1] if len(parts) > 1 else None
    return None


def _running_instance(pid_file: Path) -> int | None:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid() or _process_state(pid) in {None, "T", "Z", "X"}:
        return None
    return pid


def _ask_running_instance_to_show() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(_INSTANCE_NAME)
    if not socket.waitForConnected(400):
        return False
    socket.write(b"show\n")
    socket.flush()
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True


def _listen_for_activation(window: MainWindow, pid_file: Path) -> QLocalServer | None:
    QLocalServer.removeServer(_INSTANCE_NAME)
    server = QLocalServer()
    if not server.listen(_INSTANCE_NAME):
        return None

    def activate() -> None:
        connection = server.nextPendingConnection()
        window.show_normal()
        if connection is not None:
            connection.disconnectFromServer()

    server.newConnection.connect(activate)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    os.chmod(pid_file, 0o600)
    return server


def _reap_stopped_copies() -> None:
    """Remove frozen copies. A stopped process keeps a dead icon in the top bar."""
    me = os.getpid()
    needle = str(ROOT / "main.py")
    proc = Path("/proc")
    if not proc.is_dir():
        return
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me or _process_state(pid) not in {"T", "Z", "X"}:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if needle not in command:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = AppPaths()
    setup_logging(args.log_level, paths.log_file)
    _reap_stopped_copies()
    pid_file = paths.log_file.parent / "instance.pid"
    if _running_instance(pid_file) is not None and _ask_running_instance_to_show():
        return 0
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Exchange Calendar")
    app.setApplicationDisplayName("Exchange Calendar")
    app.setOrganizationName("exchange-calendar")
    app.setDesktopFileName("exchange-calendar")
    try:
        from app.desktop_launch import install_launcher

        install_launcher()
    except Exception:
        logging.getLogger(__name__).warning("The dock launcher could not be installed.", exc_info=True)
    apply_theme(app, load_config(paths.config_file).theme)
    window = MainWindow(demo=args.demo, paths=paths)
    server = _listen_for_activation(window, pid_file)

    def cleanup() -> None:
        window._remove_tray()
        pid_file.unlink(missing_ok=True)
        if server is not None:
            server.close()

    app.aboutToQuit.connect(cleanup)
    if window.should_start_minimized():
        window.notifications.show_message(
            "Exchange Calendar",
            "The calendar started in the tray. Click the icon to open it.",
        )
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
