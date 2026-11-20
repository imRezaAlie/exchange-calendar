"""The installed command starts the app without activating the virtual environment."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from app.desktop_launch import install_command


class LauncherCommandTests(unittest.TestCase):
    def test_command_uses_the_project_python_and_forwards_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "My Calendar"
            python = root / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            destination = Path(temporary) / "bin" / "exchange-calendar"

            installed = install_command(root, destination)

            self.assertEqual(installed, destination)
            text = destination.read_text(encoding="utf-8")
            self.assertIn(f"'{python}'", text)
            self.assertIn(f"'{root / 'main.py'}'", text)
            self.assertTrue(text.endswith('"$@"\n'))
            self.assertTrue(os.access(destination, os.X_OK))
            self.assertTrue(destination.stat().st_mode & stat.S_IXUSR)
