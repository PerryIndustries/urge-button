"""Close chosen apps during a lock and for a cooldown after it. No admin rights needed."""

import csv
import io
import subprocess
import time

NO_WINDOW = 0x08000000

# Never offer or close these, whatever is typed in Settings.
PROTECTED = {
    "explorer.exe", "pythonw.exe", "python.exe", "py.exe", "windowsterminal.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "taskmgr.exe", "dwm.exe", "winlogon.exe", "csrss.exe", "svchost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe", "systemsettings.exe",
    "applicationframehost.exe", "lockapp.exe", "sihost.exe", "ctfmon.exe", "spotify.exe",
}


def normalise(name):
    name = name.strip().lower()
    if name and not name.endswith(".exe"):
        name += ".exe"
    return name


def running_apps():
    """Exe names of programs with a visible window, for the Settings picker."""
    try:
        out = subprocess.run(["tasklist", "/v", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             timeout=15, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = set()
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 9 and row[-1] not in ("N/A", "") and row[0].lower() not in PROTECTED:
            names.add(row[0])
    return sorted(names, key=str.lower)


class AppBlocker:
    def __init__(self):
        self.until = 0.0
        self.names = []

    def start(self, names, seconds):
        """Block `names` for at least `seconds` from now (a longer block already running is kept)."""
        self.names = [n for n in (normalise(x) for x in names) if n and n not in PROTECTED]
        self.until = max(self.until, time.time() + seconds)

    def active(self):
        return bool(self.names) and time.time() < self.until

    def remaining(self):
        return max(0, int(self.until - time.time())) if self.active() else 0

    def tick(self):
        """Close any blocked app that is running. Call every few seconds while active."""
        if not self.active():
            return
        for name in self.names:
            subprocess.run(["taskkill", "/IM", name, "/F"], capture_output=True, creationflags=NO_WINDOW)

    def stop(self):
        self.until = 0.0
