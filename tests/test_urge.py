import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sudoku  # noqa: E402
from urge_log import EventLog, format_gap, to_spotify_uri  # noqa: E402

NOW = datetime(2026, 10, 10, 15, 30)  # a Saturday afternoon


def make_log(tmp_path, stamps, now=NOW):
    log = EventLog(tmp_path / "events.json", now=lambda: now)
    log.events = [{"ts": t.isoformat(timespec="seconds"), "kind": "lock", "minutes": 3,
                   "choices": [], "intensity": None} for t in stamps]
    return log


def test_today_counts_only_since_midnight(tmp_path):
    log = make_log(tmp_path, [NOW - timedelta(hours=1), NOW.replace(hour=0, minute=1),
                              NOW.replace(hour=0, minute=0) - timedelta(minutes=1)])
    assert log.today() == 2


def test_yesterday_by_now_ignores_yesterday_evening(tmp_path):
    y = NOW - timedelta(days=1)
    log = make_log(tmp_path, [y.replace(hour=9), y.replace(hour=22)])
    assert log.yesterday_by_now() == 1


def test_week_starts_monday(tmp_path):
    monday = datetime(2026, 10, 5, 8)
    log = make_log(tmp_path, [monday, monday - timedelta(hours=9)])
    assert log.this_week() == 1


def test_longest_gap_includes_the_current_stretch(tmp_path):
    log = make_log(tmp_path, [NOW - timedelta(hours=10), NOW - timedelta(hours=9)])
    assert log.longest_gap() == 9 * 3600
    assert log.since_last() == 9 * 3600


def test_by_hour_and_heat(tmp_path):
    log = make_log(tmp_path, [NOW.replace(hour=14, minute=5), NOW.replace(hour=14, minute=50),
                              NOW - timedelta(days=1)])
    assert log.by_hour()[14] == 2 and sum(log.by_hour()) == 2
    heat = log.heat(30)
    assert heat[NOW.weekday()][14] == 2 and sum(map(sum, heat)) == 3


def test_intensity_average_and_choices(tmp_path):
    log = make_log(tmp_path, [NOW - timedelta(hours=2), NOW - timedelta(hours=1)])
    a, b = log.events
    log.record_intensity(a, 2)
    log.record_intensity(b, 4)
    log.record_choice(a, "walk")
    log.record_choice(a, "walk")
    log.record_logged(intensity=3)
    assert log.intensity_per_day(3)[-1] == (NOW.date(), 3.0)
    counts = log.choice_counts()
    assert counts["walk"] == 1 and counts["on_own"] == 1


def test_events_persist(tmp_path):
    log = make_log(tmp_path, [])
    log.record_press(3)
    again = EventLog(tmp_path / "events.json", now=lambda: NOW)
    assert len(again.events) == 1 and again.events[0]["kind"] == "lock"


def test_format_gap():
    assert format_gap(30) == "just now"
    assert format_gap(5 * 60) == "5m"
    assert format_gap(2 * 3600 + 14 * 60) == "2h 14m"
    assert format_gap(26 * 3600) == "1d 2h"


def test_spotify_links():
    assert to_spotify_uri("https://open.spotify.com/intl-de/playlist/abc?si=x") == "spotify:playlist:abc"
    assert to_spotify_uri("") == "spotify:"
    assert to_spotify_uri("spotify:album:xyz") == "spotify:album:xyz"


def test_sudoku_solution_is_valid_and_checker_flags_clashes():
    puzzle, solution = sudoku.make_puzzle(random.Random(3))
    assert sudoku.is_valid_solution(solution)
    blanks = [(r, c) for r in range(9) for c in range(9) if puzzle[r][c] == 0]
    right = {rc: solution[rc[0]][rc[1]] for rc in blanks}
    assert sudoku.check(right, puzzle) == (set(), 0)
    r, c = blanks[0]
    clash = next(v for v in puzzle[r] if v)  # a digit already given in that row
    wrong, empty = sudoku.check({(r, c): clash}, puzzle)
    assert (r, c) in wrong and empty == len(blanks) - 1


def test_key_blocker_rules():
    if sys.platform != "win32":
        return
    from winapi import VK_ESCAPE, VK_F4, VK_LWIN, VK_TAB, KeyBlocker
    block = KeyBlocker.should_block
    assert block(VK_LWIN, False, False)
    assert block(VK_TAB, True, False) and block(VK_F4, True, False)
    assert block(VK_ESCAPE, False, True)
    assert not block(VK_TAB, False, False)
    assert not block(ord("A"), False, False)
