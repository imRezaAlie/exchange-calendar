# Exchange Calendar

A desktop calendar for Ubuntu. It reads an on-premises Microsoft Exchange calendar over Exchange Web Services, shows the day as a time grid or an agenda, and highlights meetings that overlap.

The window is a native PySide6 application with a monospace typeface. It does not use Electron, a browser, Microsoft Graph, or Microsoft 365. The calendar is read-only: it cannot accept, decline, edit, or delete meetings.

## Features

- Day, week, month, and agenda views. The week starts on Monday unless you change it in Settings.
- Previous, Today, and Next. Day view steps one day. Week and agenda step one week. Month view steps one month. Today returns to the current period.
- A now-and-next bar for the meeting in progress and the one that follows.
- Meeting details: time, organizer, location, attendees, status, description, and a Join button when the item contains a meeting link.
- Overlapping meetings in red, with the other meeting’s name and the overlap length.
- Local tasks, with optional reminder times. Completing or deleting a task cancels its alarm. Unfinished tasks move to the next day and keep the same clock time.
- Manual refresh, or automatic refresh every 5 or 10 minutes, without freezing the window.
- The last successful calendar stays on screen when Exchange cannot be reached.
- Light and dark themes with the same layout.
- A demo calendar, including overlapping meetings, with no Exchange account.
- An application launcher and icon so the calendar can be pinned to the Ubuntu dock.

The Status column shows the connection and the refresh schedule. The application reads the calendar only and does not open the inbox.

## Requirements

- Ubuntu 22.04 or newer
- Python 3.11 or newer
- A desktop session for the window, the tray, and the login keyring

`install.sh` installs the system packages the application needs: Python’s virtual environment, Ubuntu Mono and DejaVu Sans Mono, the Qt libraries used by PySide6, and the login keyring. Kerberos packages are optional and are not installed unless you follow the Kerberos steps below.

## Install

```bash
git clone <repository-url>
cd exchange-calendar
chmod +x install.sh
./install.sh
```

The script creates `.venv`, installs the Python dependencies from `requirements.txt`, runs the unit tests, and installs the dock icon at `~/.local/share/applications/exchange-calendar.desktop`. It also installs `~/.local/bin/exchange-calendar`, which starts the application with the virtual environment’s Python.

Open **Exchange Calendar** from the app grid. Right-click it and choose **Add to Favorites** to pin it to the dock. You do not need to activate `.venv` or run `python main.py`.

The same command works from a terminal, including the sample calendar:

```bash
~/.local/bin/exchange-calendar
~/.local/bin/exchange-calendar --demo
```

A second launch focuses the window that is already running. Closing the window quits the application and removes its icon from the top bar, unless “Keep running in the tray when the window is closed” is turned on.

## Connect to on-premises Exchange

Open **Settings** once. The password and the connection details are encrypted and loaded on the next start. The login keyring holds the secret when it is available. Nothing secret is written to `config.json`, the SQLite cache, the log, or this repository.

| Setting | Example |
| --- | --- |
| Email | `username@company.com` |
| Username | `DOMAIN\username` |
| Domain | `DOMAIN` |
| EWS URL | `https://exchange.company.com/EWS/Exchange.asmx` |
| Authentication | NTLM, Basic over HTTPS, or Kerberos |
| Autodiscover | On when the server publishes Autodiscover |

NTLM is the usual choice for an on-premises server. Basic authentication is used only when you select it, and the EWS URL must be HTTPS. Certificate verification is always on. If the server uses a private certificate authority, choose that CA bundle in Settings.

Autodiscover is tried first when it is enabled. If it fails and an EWS URL is present, the application connects to that URL.

Kerberos uses an existing ticket. Install the system headers and the optional package, then create a ticket:

```bash
sudo apt install libkrb5-dev gcc python3-dev
source .venv/bin/activate
pip install requests-gssapi
kinit username@REALM
```

Select Kerberos in Settings. A password is not required when `kinit` has already produced a ticket.

Use **Test Connection** before saving. A successful test only confirms the mailbox can be opened. It does not read mail.

`config.example.json` lists the saved fields. The real file is created at `~/.config/exchange-calendar/config.json` and is readable only by your user.

## Views

The date at the top of the window is always today. The period under the navigation buttons is the day, week, or month you are viewing. Choosing a day in the month or week grid opens that day.

Under Now and Next, Open lists the remaining gaps inside the 08:00–18:00 Tehran workday. Cancelled meetings, declined responses, free entries, and all-day events do not fill those gaps. Gaps shorter than 15 minutes are left out. When today has no 30-minute or 60-minute opening left, Later names the first one still available before the week ends.

Keyboard shortcuts:

| Shortcut | Action |
| --- | --- |
| Ctrl+Left or Alt+Left | Previous day, week, or month |
| Ctrl+Right or Alt+Right | Next day, week, or month |
| Ctrl+T | Today |
| Ctrl+1 | Day view |
| Ctrl+2 | Week view |
| Ctrl+3 | Month view |
| Ctrl+4 | Agenda view |
| F5 or Ctrl+R | Refresh |
| Ctrl+, | Settings |

## Conflicts

Two meetings conflict when the later start is before the earlier end. A meeting that ends at 10:00 does not conflict with one that starts at 10:00.

By default the detector ignores:

- cancelled meetings
- free entries
- declined responses
- all-day events

Tentative meetings are included unless you turn that off. All-day events can be included from Settings. Busy, out-of-office, and working-elsewhere entries are included. Each occurrence of a recurring series is compared on its own. Times stay timezone-aware, including daylight-saving changes and meetings that cross midnight.

A conflicting meeting is shown with a red background, a warning marker, and the other meeting’s name. Open it to see every meeting in the overlap and the shared interval. When three or more meetings overlap, the dialog lists each pair and the interval common to all of them when one exists.

## Refresh and offline use

Auto refresh is on by default at a 5 minute interval. You can switch it to 10 minutes or turn it off. Changing the interval restarts the timer. Manual refresh works either way. A refresh that is already running is not started again.

Exchange work runs on a background thread. The previous calendar stays visible if the server times out or rejects the connection. The calendar column then says that cached meetings are being shown. The cache is `~/.local/share/exchange-calendar/cache.sqlite`, mode `0600`, separated by mailbox. Passwords are not stored in it. Events outside the retention window, 60 days by default, are removed.

## Reminders, alarms, and tasks

Meeting reminders use their own 30-second clock, separate from the Exchange refresh. The default is a bell 10 minutes before the meeting and again when it starts. Choose 30, 15, 10, 5 minutes before, or the start time, under Settings → Reminders & Alarms. Join reminder adds one more alarm, 2, 5, or 10 minutes before, for a meeting that has a join link. Off leaves that extra alarm out. A conflict names the other meeting. Join opens the link only after you click it. Snooze waits 5, 10, 15, or 30 minutes. Dismissed reminders stay quiet.

Tasks live under the Tasks button. Set a reminder time, or leave the reminder off. The bell is one of four sounds played through PulseAudio or PipeWire. Mute in the tray menu keeps the visual reminder. The alarm still appears when the window is minimized. If Exchange is offline, the reminder says it came from the saved calendar.

## Tray

Turn on “Keep running in the tray when the window is closed” in Settings to leave the calendar running after the window closes. Click the icon, or choose Open Calendar, to bring the window back. Exit in that menu quits the application.

## Development

```bash
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

The tests cover conflict detection, refresh and cache behavior, alarms, the time grid, and an offscreen window. Demo mode and the tests do not need an Exchange server. Test Connection and a live calendar need your own server.

Do not commit `.venv`, `__pycache__`, logs, the SQLite cache, or a filled-in `config.json`. Those paths are listed in `.gitignore`. Passwords and account details stay in the user keyring and under `~/.config` and `~/.local`.

## Optional standalone build

```bash
chmod +x build_executable.sh
./build_executable.sh
```

The application is created at `dist/exchange-calendar/exchange-calendar`. PyInstaller can also build a single file; that starts more slowly because Qt is unpacked on each launch. Run `./install.sh` before the build script.

## Layout

```text
exchange-calendar/
├── main.py                 application entry point
├── install.sh              Ubuntu install, tests, and launcher
├── build_executable.sh     optional PyInstaller build
├── requirements.txt
├── config.example.json     settings fields, with no secrets
├── app/
│   ├── config.py           preferences and XDG paths
│   ├── models.py
│   ├── desktop_launch.py   application icon, menu launcher, and command
│   ├── calendar/           dates, demo data, and conflict detection
│   ├── exchange/           EWS authentication and calendar reading
│   ├── services/           refresh, alarms, and notifications
│   ├── storage/            SQLite cache and the system keyring
│   └── ui/                 window, views, and monospace theme
└── tests/
```

Runtime files, outside this repository:

| Path | Contents |
| --- | --- |
| `~/.config/exchange-calendar/config.json` | Preferences and connection fields, mode `0600` |
| `~/.local/share/exchange-calendar/` | Calendar cache and local tasks |
| `~/.local/state/exchange-calendar/exchange-calendar.log` | Log, with passwords and authorization headers redacted |
| Login keyring | Encrypted password and account profile |

## Troubleshooting

- **Authentication failed.** Check the username form `DOMAIN\username`, the password, and that NTLM is enabled on the EWS virtual directory.
- **Autodiscover failed.** Paste the EWS URL. It normally ends in `/EWS/Exchange.asmx`.
- **TLS certificate verification failed.** Add the server’s CA file in Settings. Verification cannot be turned off.
- **The window is empty.** Use `~/.local/bin/exchange-calendar --demo` to confirm the interface, then Test Connection.
- **The keyring did not save the password.** Unlock the login keyring and save Settings again. The application also keeps an encrypted copy for the next launch.
- **A dead icon stays in the top bar.** Close the window, or choose Exit in the tray menu. Do not leave a stopped `exchange-calendar` process in a terminal.
- **Logs.** `~/.local/state/exchange-calendar/exchange-calendar.log`. Exchange library logging stays at warning level.
