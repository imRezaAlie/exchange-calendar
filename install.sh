#!/usr/bin/env bash
# Install Exchange Calendar on Ubuntu and register its application launcher.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11+ is required. This system has {sys.version.split()[0]}.")
print(f"Python {sys.version.split()[0]} found.")
PY

# Qt, the login keyring, and a monospace font. Ubuntu Mono is preferred.
# DejaVu Sans Mono is the fallback used by the application font list.
APT_PACKAGES=(
  python3
  python3-venv
  python3-pip
  ca-certificates
  fonts-ubuntu
  fonts-dejavu-core
  libdbus-1-3
  libegl1
  libgl1
  libsecret-1-0
  libxcb-cursor0
  libxkbcommon0
  gnome-keyring
)

install_system_packages() {
  if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg-query >/dev/null 2>&1; then
    echo "apt was not found. Install these packages with your system package manager, then run this script again:" >&2
    printf '  %s\n' "${APT_PACKAGES[@]}" >&2
    exit 1
  fi

  local missing=()
  local pkg
  for pkg in "${APT_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
      missing+=("$pkg")
    fi
  done
  if ((${#missing[@]} == 0)); then
    echo "System packages are already installed."
    return
  fi

  echo "Installing system packages: ${missing[*]}"
  if [[ "$(id -u)" -eq 0 ]]; then
    apt-get update
    apt-get install -y "${missing[@]}"
  elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
  else
    echo "These packages are missing, and sudo is not available:" >&2
    printf '  %s\n' "${missing[@]}" >&2
    echo "Install them, then run ./install.sh again." >&2
    exit 1
  fi
}

install_system_packages

if [[ ! -x .venv/bin/python ]]; then
  rm -rf .venv
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "Running unit tests..."
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v

echo "Installing the application icon and launcher..."
QT_QPA_PLATFORM=offscreen .venv/bin/python -c "from app.desktop_launch import install_application; print(install_application())"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" || true
fi

echo
echo "Installation complete."
echo "Open the app grid and start Exchange Calendar."
echo "Right-click it and choose Add to Favorites to pin it to the dock."
echo "The virtual environment does not need to be activated."
echo
echo "The same launcher works from a terminal:"
echo "  ~/.local/bin/exchange-calendar"
echo "  ~/.local/bin/exchange-calendar --demo"
echo
echo "Then open Settings and enter the on-premises Exchange connection:"
echo "  Email, DOMAIN\\\\username, EWS URL, and NTLM, Basic, or Kerberos."
echo "The password and account are encrypted on this computer."
echo "Nothing secret is written into this repository."
echo
echo "Kerberos also needs the system libraries, an extra Python package, and a ticket:"
echo "  sudo apt install libkrb5-dev gcc python3-dev"
echo "  source .venv/bin/activate"
echo "  pip install requests-gssapi"
echo "  kinit username@REALM"
