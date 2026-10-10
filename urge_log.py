"""Storage and stats for the Urge Button. No UI and no Windows calls, so it is testable anywhere.

Every urge is one event in events.json:
    {"ts": "2026-10-10T21:14:03", "kind": "lock" | "logged", "minutes": 3,
     "choices": ["walk", ...], "intensity": 1-5 or null}
"lock" = the button was pressed and the screen locked; "logged" = handled it without locking.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "UrgeButton"
CONFIG_PATH = APP_DIR / "config.json"
EVENTS_PATH = APP_DIR / "events.json"

MAX_LOCK_MINUTES = 30

DEFAULT_CONFIG = {
    "lock_minutes": 3,
    "spotify_uri": "spotify:",
    "friends": [],
    "button_x": None,
    "button_y": None,
    "button_monitor": None,      # Windows device name; None = the main monitor
    "button_anchor": "bottom-right",  # a placement.ANCHORS key, or "custom" after a drag
    "lock_monitor": None,        # where the lock-screen message shows; None = the main monitor
}

OPTIONS = [
    ("walk", "Go for a walk", "Shoes on. Out the door."),
    ("spotify", "Play some music", "Opens Spotify and hits play."),
    ("sudoku", "Play Sudoku", "Give your hands something to do."),
    ("friend", "Reach out to a friend", "Send someone a message."),
]
OPTION_NAMES = {key: title for key, title, _ in OPTIONS}


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def clamp_minutes(value):
    try:
        return max(1, min(MAX_LOCK_MINUTES, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_CONFIG["lock_minutes"]


def load_config(path=CONFIG_PATH):
    cfg = dict(DEFAULT_CONFIG)
    saved = load_json(path, {})
    cfg.update(saved)
    if "button_anchor" not in saved and saved.get("button_x") is not None:
        cfg["button_anchor"] = "custom"  # dragged before anchors existed: keep it where it was
    cfg["lock_minutes"] = clamp_minutes(cfg.get("lock_minutes"))
    return cfg


def to_spotify_uri(text):
    """open.spotify.com/playlist/ID?si=... -> spotify:playlist:ID (opens in the app, not a browser)."""
    if not text:
        return "spotify:"
    if "open.spotify.com/" in text:
        path = text.split("open.spotify.com/", 1)[1].split("?", 1)[0].strip("/")
        parts = [p for p in path.split("/") if p and not p.startswith("intl-")]
        if len(parts) >= 2:
            return f"spotify:{parts[0]}:{parts[1]}"
    return text


def format_gap(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return "just now"
    m = seconds // 60
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m" if m else f"{h}h"
    d, h = divmod(h, 24)
    return f"{d}d {h}h" if h else f"{d}d"


def start_of_day(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


class EventLog:
    def __init__(self, path=EVENTS_PATH, now=datetime.now):
        self.path = Path(path)
        self.now = now
        self.events = load_json(self.path, [])

    # -- writing

    def _add(self, kind, minutes, intensity=None):
        event = {
            "ts": self.now().isoformat(timespec="seconds"),
            "kind": kind,
            "minutes": minutes,
            "choices": [],
            "intensity": intensity,
        }
        self.events.append(event)
        self.save()
        return event

    def record_press(self, minutes):
        return self._add("lock", minutes)

    def record_logged(self, intensity=None):
        return self._add("logged", 0, intensity)

    def record_choice(self, event, choice):
        if choice not in event["choices"]:
            event["choices"].append(choice)
            self.save()

    def record_intensity(self, event, intensity):
        event["intensity"] = int(intensity)
        self.save()

    def save(self):
        save_json(self.path, self.events)

    # -- reading

    def times(self):
        out = []
        for e in self.events:
            try:
                out.append((datetime.fromisoformat(e["ts"]), e))
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda p: p[0])
        return out

    def count_between(self, start, end):
        return sum(1 for t, _ in self.times() if start <= t < end)

    def today(self):
        now = self.now()
        return self.count_between(start_of_day(now), now + timedelta(seconds=1))

    def yesterday_by_now(self):
        """Urges yesterday up to the same time of day - a fair comparison mid-day."""
        now = self.now()
        y = now - timedelta(days=1)
        return self.count_between(start_of_day(y), y + timedelta(seconds=1))

    def week_start(self, dt):
        return start_of_day(dt) - timedelta(days=dt.weekday())

    def this_week(self):
        now = self.now()
        return self.count_between(self.week_start(now), now + timedelta(seconds=1))

    def last_week_by_now(self):
        now = self.now()
        then = now - timedelta(days=7)
        return self.count_between(self.week_start(then), then + timedelta(seconds=1))

    def last_time(self):
        ts = self.times()
        return ts[-1][0] if ts else None

    def since_last(self):
        last = self.last_time()
        return None if last is None else (self.now() - last).total_seconds()

    def longest_gap(self):
        """Longest stretch between urges in seconds, counting the stretch you are on right now."""
        ts = [t for t, _ in self.times()]
        if not ts:
            return None
        gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
        gaps.append((self.now() - ts[-1]).total_seconds())
        return max(gaps)

    def per_day(self, days):
        today = self.now().date()
        counts = {today - timedelta(days=i): 0 for i in range(days)}
        for t, _ in self.times():
            if t.date() in counts:
                counts[t.date()] += 1
        return sorted(counts.items())

    def by_hour(self, day=None):
        day = day or self.now().date()
        counts = [0] * 24
        for t, _ in self.times():
            if t.date() == day:
                counts[t.hour] += 1
        return counts

    def heat(self, days=30):
        """7 x 24 grid [weekday][hour] of urges over the last `days` days."""
        since = start_of_day(self.now()) - timedelta(days=days - 1)
        grid = [[0] * 24 for _ in range(7)]
        for t, _ in self.times():
            if t >= since:
                grid[t.weekday()][t.hour] += 1
        return grid

    def intensity_per_day(self, days):
        today = self.now().date()
        buckets = {today - timedelta(days=i): [] for i in range(days)}
        for t, e in self.times():
            v = e.get("intensity")
            if t.date() in buckets and isinstance(v, (int, float)):
                buckets[t.date()].append(v)
        return [(d, sum(v) / len(v) if v else None) for d, v in sorted(buckets.items())]

    def choice_counts(self, days=None):
        since = None if days is None else start_of_day(self.now()) - timedelta(days=days - 1)
        counts = {key: 0 for key, _, _ in OPTIONS}
        counts["on_own"] = 0
        for t, e in self.times():
            if since and t < since:
                continue
            if e.get("kind") == "logged":
                counts["on_own"] += 1
            for c in e.get("choices", []):
                counts[c] = counts.get(c, 0) + 1
        return counts
