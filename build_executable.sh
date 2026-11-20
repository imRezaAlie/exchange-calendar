#!/usr/bin/env bash
# Build a standalone Linux application directory with PyInstaller.
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./install.sh first." >&2
  exit 1
fi

.venv/bin/python -m pip install 'pyinstaller>=6.0'
.venv/bin/pyinstaller --noconfirm --clean --windowed --name exchange-calendar \
  --collect-submodules exchangelib \
  --hidden-import keyring.backends.SecretService \
  --hidden-import keyring.backends.kwallet \
  main.py

echo
echo "Executable: dist/exchange-calendar/exchange-calendar"
echo "A single-file build is also possible, but it starts more slowly:"
echo "  .venv/bin/pyinstaller --noconfirm --clean --windowed --onefile --name exchange-calendar main.py"
