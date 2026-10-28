"""Storage and stats for the Urge Button. No UI and no Windows calls, so it is testable anywhere.

Every urge is one event in events.json:
    {"ts": "2026-10-10T21:14:03", "kind": "lock" | "logged", "minutes": 3,
     "choices": ["walk", ...], "intensity": 1-5 or null}
"lock" = the button was pressed and the screen locked; "logged" = handled it without locking.

A Bored press is an event in the same file with "kind": "bored" and "choices": [what you picked] (a
BORED_IDEAS id, or the text of your own idea). It is tracked on its own: nothing that counts urges
counts it. Picking an idea runs it as an activity in the panel, and how that went lands on the same
event: "done" (True = finished, False = stopped early), "seconds" spent, "note" (what you wrote down,
noticed outside, or are practicing) and "amount" (pages read). All four are optional.
"""

import json
import math
import os
import random
import time
import uuid
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
    "reasons": [],               # your own lines, shown on the lock screen
    "reason_image": "",          # optional PNG/GIF shown above them
    "heads_up": True,            # warn ~10 minutes before an hour that's usually hard
    "plan": "",                  # what you'll do when a hard hour comes; shown in the heads-up
    "block_apps": [],            # exe names closed during a lock and the cooldown after it
    "block_minutes": 30,         # cooldown after a lock ends
    "sync_repo": "PerryIndustries/urge-data",
    "sync_token": "",            # blank = use this computer's GitHub CLI login
    "sync": True,
    "escalate": True,            # longer locks when urges come close together
    "bored_ideas": [],           # your own lines for the Bored button; blank = the BORED_IDEAS defaults
    "minimized": False,          # the strip is folded down to one small dot
    "dot_x": None,               # where the dot was last dragged to; None = beside the strip's own spot
    "dot_y": None,
}

HEADS_UP_MINUTES = 10
CLUSTER_WINDOW_MINUTES = 30
CLUSTER_LADDER = (5, 10)  # minutes for the 2nd, and the 3rd-or-later, lock inside the window


def cluster_minutes(base, recent_locks):
    """Lock length when urges come close together: your usual length, then at least 5, then at least 10."""
    if recent_locks <= 0:
        return base
    step = CLUSTER_LADDER[min(recent_locks, len(CLUSTER_LADDER)) - 1]
    return min(MAX_LOCK_MINUTES, max(base, step))


def hour_name(h):
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def heads_up_due(now, risky, since_last, last_key):
    """The key of a heads-up to show now, or None.

    Fires in the last HEADS_UP_MINUTES before a risky hour starts, once per hour per day, and not
    when an urge was logged in the last 30 minutes (you're already dealing with it).
    """
    if now.minute < 60 - HEADS_UP_MINUTES:
        return None
    upcoming = (now + timedelta(minutes=HEADS_UP_MINUTES)).replace(minute=0, second=0, microsecond=0)
    if upcoming.hour not in risky:
        return None
    if since_last is not None and since_last < 30 * 60:
        return None
    key = f"{upcoming:%Y-%m-%d %H}"
    return None if key == last_key else key

OPTIONS = [
    ("breathe", "Breathe with me", "One slow minute. Follow the circle."),
    ("walk", "Go for a walk", "Shoes on. Out the door."),
    ("spotify", "Play some music", "Opens Spotify and hits play."),
    ("sudoku", "Play Sudoku", "Give your hands something to do."),
    ("friend", "Reach out to a friend", "Send someone a message."),
]
OPTION_NAMES = {key: title for key, title, _ in OPTIONS}

TRIGGERS = ["Bored", "Stressed", "Lonely", "Tired", "Anxious", "Late night", "After gaming", "Something I saw", "Other"]

# The Bored button's default ideas. "sudoku" opens the Sudoku and "music" puts Spotify on; the rest are nudges.
BORED_IDEAS = [
    ("sudoku", "Play Sudoku"),
    ("stretch", "Stretch for 2 minutes"),
    ("tidy", "Tidy one surface"),
    ("water", "Drink a glass of water"),
    ("outside", "Step outside for 5 minutes"),
    ("read", "Read a few pages"),
    ("music", "Put music on"),
    ("practice", "Practice something you're learning"),
    ("write", "Write down what's on your mind"),
    ("friend", "Text a friend"),
]
BORED_NAMES = {key: text for key, text in BORED_IDEAS}
BORED_NAMES["none"] = "Just logged it"
BORED_KEYS = {text.lower(): key for key, text in BORED_IDEAS}
BORED_IDEAS_PICKED = 3        # how many ideas the panel shows at once
BORED_URGE_WINDOW_MINUTES = 60  # an urge this soon after a Bored press counts as "bored, then an urge"

BORED_LINES = [
    "Nice. Five minutes, then see how you feel.",
    "Good call. Go do the thing.",
    "That'll do it. Off you go.",
    "Small thing, real thing. Enjoy it.",
]

# What happens once you pick an idea. Sudoku and music open something else; everything else runs in the panel.
JUMPS = ("sudoku", "music")
STRETCHES = ["Neck rolls", "Shoulder rolls", "Reach up tall", "Side bend, each side", "Forward fold", "Chest opener"]
STRETCH_SECONDS = 20
SURFACES = ["your desk", "the nightstand", "the kitchen counter", "one shelf", "the floor around you"]
ACTIVITY_SECONDS = {
    "stretch": len(STRETCHES) * STRETCH_SECONDS,
    "outside": 5 * 60,
    "tidy": 5 * 60,
    "read": 10 * 60,
    "practice": 10 * 60,
}
CUSTOM_SECONDS = 5 * 60  # your own ideas get a plain five-minute timer

FINISH_LINES = {
    "stretch": "Looser already? Two minutes well spent.",
    "write": "It's out of your head and on the page.",
    "outside": "Fresh air beats the feed every time.",
    "tidy": "One surface clearer. That counts.",
    "read": "A few pages further than you were.",
    "practice": "Ten minutes better at it than you were.",
    "friend": "Sent. That's a real connection, not a scroll.",
    "water": "Hydrated and a little less bored.",
}
DEFAULT_FINISH_LINES = [
    "That's five minutes well spent.",
    "Done is done. Nice one.",
    "Small thing, real thing. Finished.",
]
STOP_LINES = [
    "Stopped early. Noticing still counts.",
    "Even a minute off the scroll is a minute.",
]


def finish_line(key, rng=random):
    """The one line said when an activity is finished."""
    return FINISH_LINES.get(key) or rng.choice(DEFAULT_FINISH_LINES)


def activity_seconds(key):
    """How long an idea's timer runs; your own ideas get the plain five minutes."""
    return ACTIVITY_SECONDS.get(key, CUSTOM_SECONDS)


def stretch_at(elapsed):
    """Where the stretch routine is `elapsed` seconds in: (index, name, next name or None, seconds left in it).

    None once the routine is over (or before it starts).
    """
    i = int(elapsed // STRETCH_SECONDS)
    if elapsed < 0 or i >= len(STRETCHES):
        return None
    left = STRETCH_SECONDS - (elapsed - i * STRETCH_SECONDS)
    return i, STRETCHES[i], STRETCHES[i + 1] if i + 1 < len(STRETCHES) else None, left


def clock_text(seconds):
    m, s = divmod(int(math.ceil(max(0, seconds))), 60)
    return f"{m}:{s:02d}"


class Countdown:
    """A countdown that reads the clock instead of counting ticks, so a window that was put away stays right."""

    def __init__(self, seconds, now=time.monotonic):
        self.total = seconds
        self.now = now
        self.started = now()
        self.paused_at = None
        self.paused_for = 0.0

    @property
    def paused(self):
        return self.paused_at is not None

    def elapsed(self):
        end = self.paused_at if self.paused else self.now()
        return max(0.0, end - self.started - self.paused_for)

    def remaining(self):
        return max(0.0, self.total - self.elapsed())

    def pause(self):
        if not self.paused:
            self.paused_at = self.now()

    def resume(self):
        if self.paused:
            self.paused_for += self.now() - self.paused_at
            self.paused_at = None


def bored_ideas(cfg):
    """The ideas to offer: your own lines from Settings, or the defaults when there are none."""
    own = [line.strip() for line in (cfg.get("bored_ideas") or []) if line.strip()]
    return own or [text for _, text in BORED_IDEAS]


def bored_key(text):
    """What gets logged for an idea: a built-in's id when the text is one of them, else the text itself."""
    return BORED_KEYS.get(text.strip().lower(), text.strip())


def bored_name(key):
    return BORED_NAMES.get(key, key)


def pick_ideas(ideas, avoid=(), n=BORED_IDEAS_PICKED, rng=random):
    """`n` different ideas at random, steering clear of the ones just shown when there are enough to do so."""
    ideas = list(dict.fromkeys(ideas))  # keep order, drop duplicates
    fresh = [i for i in ideas if i not in avoid]
    pool = fresh if len(fresh) >= n else ideas
    return rng.sample(pool, min(n, len(pool)))


def is_urge(event):
    """Everything in the log is an urge except a Bored press (the oldest events have no kind at all)."""
    return event.get("kind", "lock") != "bored"


def strength(event):
    """How strong the urge was: the rating at the start when there is one, else the end rating."""
    for key in ("intensity_start", "intensity"):
        v = event.get(key)
        if isinstance(v, (int, float)):
            return v
    return None


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
        self.on_change = None  # called after every local change (the app uses it to sync)
        self.events = load_json(self.path, [])
        if any("id" not in e for e in self.events):  # ids came in with sync; give older events one
            for e in self.events:
                e.setdefault("id", uuid.uuid4().hex)
                e.setdefault("u", 0)
            save_json(self.path, self.events)

    # -- writing

    def _stamp(self, event):
        event["u"] = int(time.time() * 1000)

    def _changed(self, event):
        self._stamp(event)
        self.save()
        if self.on_change:
            self.on_change()

    def _add(self, kind, minutes, intensity_start=None, triggers=None):
        event = {
            "id": uuid.uuid4().hex,
            "ts": self.now().isoformat(timespec="seconds"),
            "kind": kind,
            "minutes": minutes,
            "choices": [],
            "intensity_start": intensity_start,  # how strong when it hit
            "intensity": None,                   # how strong when the lock ended
            "triggers": list(triggers or []),
        }
        self.events.append(event)
        self._changed(event)
        return event

    def record_press(self, minutes):
        return self._add("lock", minutes)

    def record_logged(self, intensity=None, triggers=None):
        return self._add("logged", 0, intensity, triggers)

    def record_bored(self):
        """A Bored press. What you pick goes into its choices (record_choice); dismissing it leaves them empty."""
        return self._add("bored", 0)

    def record_start_intensity(self, event, intensity):
        event["intensity_start"] = int(intensity)
        self._changed(event)

    def record_triggers(self, event, triggers):
        event["triggers"] = list(triggers)
        self._changed(event)

    def record_choice(self, event, choice):
        if choice not in event["choices"]:
            event["choices"].append(choice)
            self._changed(event)

    def record_intensity(self, event, intensity):
        event["intensity"] = int(intensity)
        self._changed(event)

    # how a Bored activity went

    def record_outcome(self, event, done, seconds):
        """How an activity ended: finished (Done) or stopped early, and the seconds spent on it."""
        event["done"] = bool(done)
        event["seconds"] = int(round(max(0, seconds)))
        self._changed(event)

    def record_note(self, event, text):
        """What you wrote, noticed or are practicing. Blank clears it - that is how a note is deleted."""
        event["note"] = (text or "").strip() or None
        self._changed(event)

    def record_amount(self, event, amount):
        """A number that came out of an activity, like pages read."""
        event["amount"] = int(amount)
        self._changed(event)

    def save(self):
        save_json(self.path, self.events)

    # -- sync

    def shared(self):
        from sync import to_shared
        return [to_shared(e) for e in self.events if e.get("id") and e.get("ts")]

    def apply_shared(self, merged):
        """Take in a merged list from sync, updating events in place (open screens keep their references)."""
        from sync import from_shared
        mine = {e.get("id"): e for e in self.events}
        changed = False
        for s in merged:
            cur = mine.get(s["id"])
            if cur is None:
                self.events.append(from_shared(s))
                changed = True
            elif s.get("u", 0) > cur.get("u", 0):
                cur.clear()
                cur.update(from_shared(s))
                changed = True
        if changed:
            self.events.sort(key=lambda e: e.get("ts", ""))
            self.save()
        return changed

    # -- reading
    # Every stat is about urges unless asked for the Bored presses (`bored=True`): the two never mix.

    def urges(self):
        return [e for e in self.events if is_urge(e)]

    def times(self, bored=False):
        """[(time, event)] in order: the urges, or with `bored` the Bored presses."""
        out = []
        for e in self.events:
            if is_urge(e) == bored:
                continue
            try:
                out.append((datetime.fromisoformat(e["ts"]), e))
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda p: p[0])
        return out

    def count_between(self, start, end, bored=False):
        return sum(1 for t, _ in self.times(bored) if start <= t < end)

    def today(self, bored=False):
        now = self.now()
        return self.count_between(start_of_day(now), now + timedelta(seconds=1), bored)

    def yesterday_by_now(self, bored=False):
        """Urges yesterday up to the same time of day - a fair comparison mid-day."""
        now = self.now()
        y = now - timedelta(days=1)
        return self.count_between(start_of_day(y), y + timedelta(seconds=1), bored)

    def week_start(self, dt):
        return start_of_day(dt) - timedelta(days=dt.weekday())

    def this_week(self, bored=False):
        now = self.now()
        return self.count_between(self.week_start(now), now + timedelta(seconds=1), bored)

    def last_week_by_now(self, bored=False):
        now = self.now()
        then = now - timedelta(days=7)
        return self.count_between(self.week_start(then), then + timedelta(seconds=1), bored)

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

    def per_day(self, days, bored=False):
        today = self.now().date()
        counts = {today - timedelta(days=i): 0 for i in range(days)}
        for t, _ in self.times(bored):
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

    def heat(self, days=30, bored=False):
        """7 x 24 grid [weekday][hour] of urges over the last `days` days."""
        since = start_of_day(self.now()) - timedelta(days=days - 1)
        grid = [[0] * 24 for _ in range(7)]
        for t, _ in self.times(bored):
            if t >= since:
                grid[t.weekday()][t.hour] += 1
        return grid

    def intensity_per_day(self, days):
        today = self.now().date()
        buckets = {today - timedelta(days=i): [] for i in range(days)}
        for t, e in self.times():
            v = strength(e)
            if t.date() in buckets and v is not None:
                buckets[t.date()].append(v)
        return [(d, sum(v) / len(v) if v else None) for d, v in sorted(buckets.items())]

    def _since(self, days):
        return None if days is None else start_of_day(self.now()) - timedelta(days=days - 1)

    def relief_by_choice(self, days=None):
        """{choice: (average drop from start to end rating, times measured)} - how much each option helped."""
        since = self._since(days)
        drops = {}
        for t, e in self.times():
            a, b = e.get("intensity_start"), e.get("intensity")
            if (since and t < since) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                continue
            for c in e.get("choices", []) or ["none"]:
                drops.setdefault(c, []).append(a - b)
        return {c: (sum(v) / len(v), len(v)) for c, v in drops.items()}

    def trigger_counts(self, days=None):
        """[(trigger, count)] most common first, only triggers that came up."""
        since = self._since(days)
        counts = {}
        for t, e in self.times():
            if since and t < since:
                continue
            for trig in e.get("triggers", []) or []:
                counts[trig] = counts.get(trig, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def recent_locks(self, minutes=CLUSTER_WINDOW_MINUTES):
        """Locks started in the last `minutes` minutes."""
        since = self.now() - timedelta(minutes=minutes)
        return sum(1 for t, e in self.times() if t >= since and e.get("kind", "lock") == "lock")

    def calmer_days(self, days=30):
        """Days below your own daily average over the window - progress that one bad day can't erase.

        Returns {"calm": n, "of": days, "run": current run of calm days ending yesterday or today,
        "best_run": longest run in the window}, or None with no history.
        """
        per_day = self.per_day(days)
        total = sum(n for _, n in per_day)
        if not total:
            return None
        avg = total / days
        calm = [n < avg for _, n in per_day]
        best = run = 0
        for c in calm:
            run = run + 1 if c else 0
            best = max(best, run)
        # today isn't over: a calm-so-far today extends the run, a busy today doesn't break it yet
        current = 0
        for c in reversed(calm[:-1]):
            if not c:
                break
            current += 1
        if calm[-1]:
            current += 1
        return {"calm": sum(calm), "of": days, "run": current, "best_run": best}

    def risky_hours(self, days=28):
        """Hours of the day that stand out: at least 4 urges there in `days` days and twice the hourly average."""
        since = self._since(days)
        counts = [0] * 24
        for t, _ in self.times():
            if t >= since:
                counts[t.hour] += 1
        threshold = max(4, 2 * sum(counts) / 24)
        return {h for h, n in enumerate(counts) if n >= threshold}

    def week_review(self):
        """Facts about last week (Monday to Sunday), or None when there's nothing to say yet."""
        this_monday = self.week_start(self.now())
        start, prev_start = this_monday - timedelta(days=7), this_monday - timedelta(days=14)
        ts = self.times()
        last = [(t, e) for t, e in ts if start <= t < this_monday]
        prev = [t for t, _ in ts if prev_start <= t < start]
        if not last and not prev:
            return None
        per_day = [0] * 7
        hours = [0] * 24
        triggers = {}
        for t, e in last:
            per_day[t.weekday()] += 1
            hours[t.hour] += 1
            for trig in e.get("triggers", []) or []:
                triggers[trig] = triggers.get(trig, 0) + 1
        # "calmer days": below your usual daily rate over the four weeks before last week
        base = [t for t, _ in ts if start - timedelta(days=28) <= t < start]
        usual = len(base) / 28 if base else None
        relief = {k: v for k, v in self.relief_by_choice(28).items() if v[1] >= 2 and k in OPTION_NAMES}
        best = max(relief.items(), key=lambda kv: kv[1][0]) if relief else None
        return {
            "total": len(last),
            "previous": len(prev),
            "calm_days": sum(1 for n in per_day if n < usual) if usual is not None else None,
            "usual": usual,
            "quietest_day": min(range(7), key=lambda d: (per_day[d], -d)),
            "hardest_hour": max(range(24), key=lambda h: hours[h]) if any(hours) else None,
            "top_trigger": max(triggers.items(), key=lambda kv: kv[1])[0] if triggers else None,
            "best_option": (best[0], best[1][0]) if best and best[1][0] > 0 else None,
        }

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

    # -- the Bored button

    def bored_choice_counts(self, days=None):
        """[(idea key, times picked)] most picked first; "none" is a press dismissed without picking."""
        since = self._since(days)
        counts = {}
        for t, e in self.times(bored=True):
            if since and t < since:
                continue
            for c in e.get("choices") or ["none"]:
                counts[c] = counts.get(c, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def bored_picks(self, days=None):
        """[(time, event, key)] Bored presses where something was picked, oldest first; key is the first pick."""
        since = self._since(days)
        return [(t, e, e["choices"][0]) for t, e in self.times(bored=True)
                if e.get("choices") and not (since and t < since)]

    def bored_finished(self, days=30):
        """(finished, picks) over the window - picks that ran in the panel, and how many ended with Done.

        Sudoku and music just open something, so they are left out of both numbers.
        """
        picks = [e for _, e, key in self.bored_picks(days) if key not in JUMPS]
        return sum(1 for e in picks if e.get("done") is True), len(picks)

    def bored_seconds(self, days=30):
        """Seconds spent on Bored activities over the window."""
        return sum(int(e.get("seconds") or 0) for _, e, _ in self.bored_picks(days))

    def bored_idea_rows(self, days=None):
        """[(idea key, times picked, times finished)] most picked first; "none" is a press dismissed without picking."""
        since = self._since(days)
        picked, finished = {}, {}
        for t, e in self.times(bored=True):
            if since and t < since:
                continue
            for c in e.get("choices") or ["none"]:
                picked[c] = picked.get(c, 0) + 1
                if e.get("done") is True:
                    finished[c] = finished.get(c, 0) + 1
        rows = [(c, n, finished.get(c, 0)) for c, n in picked.items()]
        return sorted(rows, key=lambda r: (-r[1], r[0]))

    def bored_notes(self):
        """[(time, event)] every Bored press with a note, newest first."""
        return [(t, e) for t, e in reversed(self.times(bored=True)) if (e.get("note") or "").strip()]

    def last_note(self, key):
        """The latest note saved on a pick of `key` (what you were practicing last time), or ''."""
        for _, e in self.bored_notes():
            if (e.get("choices") or [None])[0] == key:
                return e["note"]
        return ""

    def glasses_today(self):
        """Glasses of water drunk today from the Bored button (picked water and tapped Done)."""
        start = start_of_day(self.now())
        return sum(1 for t, e, key in self.bored_picks() if key == "water" and e.get("done") is True and t >= start)

    def bored_then_urge(self, days=30, minutes=BORED_URGE_WINDOW_MINUTES):
        """(how many Bored presses had an urge within `minutes`, how many Bored presses) over the window."""
        since = self._since(days)
        urges = [t for t, _ in self.times()]
        window = timedelta(minutes=minutes)
        hit = total = 0
        for t, _ in self.times(bored=True):
            if since and t < since:
                continue
            total += 1
            if any(t < u <= t + window for u in urges):
                hit += 1
        return hit, total
