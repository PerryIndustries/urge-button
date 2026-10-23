"""The Alarm button: opens the Wake Alarm panel (C:\\Users\\Perry\\Alarm) and shows when it next rings.

The alarm lives in its own folder and scheduled tasks; this only reads its status script and launches its panel.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

FOLDER = Path.home() / "Alarm"
NO_WINDOW = 0x08000000
REFRESH_SECONDS = 5 * 60


def installed():
    return (FOLDER / "alarm_panel.py").exists()


def status():
    """The alarm's own status JSON (alarm-status.ps1), or None when it can't be read."""
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(FOLDER / "alarm-status.ps1")], capture_output=True, text=True,
                           creationflags=NO_WINDOW, timeout=60)
        return json.loads(p.stdout) if p.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def label(next_ring, now):
    """The line under the Alarm button: '9am' today, 'Sat 11am' later, 'off' with nothing set.

    next_ring is alarm-status.ps1's "next", like 'Sat Oct 24, 11:00 AM'.
    """
    if not next_ring:
        return "off"
    try:
        when = datetime.strptime(next_ring, "%a %b %d, %I:%M %p").replace(year=now.year)
    except ValueError:
        return "?"
    if when < now.replace(hour=0, minute=0, second=0, microsecond=0):  # a December alarm read in January
        when = when.replace(year=now.year + 1)
    clock = f"{when.hour % 12 or 12}" + (f":{when.minute:02d}" if when.minute else "") + ("am" if when.hour < 12 else "pm")
    return clock if when.date() == now.date() else f"{when:%a} {clock}"


def open_panel(pythonw):
    subprocess.Popen([pythonw, str(FOLDER / "alarm_panel.py")], cwd=str(FOLDER), creationflags=NO_WINDOW)
