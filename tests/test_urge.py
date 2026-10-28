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


def test_relief_by_choice_and_triggers(tmp_path):
    log = make_log(tmp_path, [NOW - timedelta(hours=3), NOW - timedelta(hours=2), NOW - timedelta(hours=1)])
    a, b, c = log.events
    for e, start, end, choice in ((a, 4, 1, "walk"), (b, 4, 3, "walk"), (c, 2, 3, "sudoku")):
        log.record_start_intensity(e, start)
        log.record_intensity(e, end)
        log.record_choice(e, choice)
    log.record_triggers(a, ["Bored", "Tired"])
    log.record_triggers(b, ["Bored"])
    relief = log.relief_by_choice()
    assert relief["walk"] == (2.0, 2)
    assert relief["sudoku"] == (-1.0, 1)
    assert log.trigger_counts() == [("Bored", 2), ("Tired", 1)]


def test_strength_prefers_the_start_rating(tmp_path):
    from urge_log import strength
    assert strength({"intensity_start": 4, "intensity": 2}) == 4
    assert strength({"intensity": 2}) == 2  # events from before start ratings existed
    assert strength({}) is None


def test_heads_up_fires_once_in_the_ten_minutes_before_a_risky_hour():
    from urge_log import heads_up_due
    at = lambda h, m: datetime(2026, 10, 10, h, m)  # noqa: E731
    assert heads_up_due(at(20, 49), {21}, None, None) is None          # too early
    key = heads_up_due(at(20, 52), {21}, None, None)
    assert key == "2026-10-10 21"
    assert heads_up_due(at(20, 55), {21}, None, key) is None           # already shown
    assert heads_up_due(at(20, 52), {22}, None, None) is None          # not a risky hour
    assert heads_up_due(at(20, 52), {21}, 10 * 60, None) is None       # just logged one
    assert heads_up_due(at(23, 55), {0}, None, None) == "2026-10-11 00"  # across midnight


def test_risky_hours_need_a_real_pattern(tmp_path):
    stamps = [NOW.replace(hour=21) - timedelta(days=d) for d in range(1, 6)]  # 9 PM five times
    stamps += [NOW.replace(hour=h) - timedelta(days=2) for h in (8, 13)]
    log = make_log(tmp_path, stamps)
    assert log.risky_hours() == {21}
    assert make_log(tmp_path, stamps[:3]).risky_hours() == set()       # three isn't a pattern yet


def test_week_review(tmp_path):
    # NOW is Saturday 10 Oct; last week = Mon 28 Sep .. Sun 4 Oct
    last_week = [datetime(2026, 9, 28, 21), datetime(2026, 9, 29, 21), datetime(2026, 10, 1, 9)]
    week_before = [datetime(2026, 9, 22, 20)] * 5
    log = make_log(tmp_path, last_week + week_before)
    log.record_triggers(log.events[0], ["Bored"])
    r = log.week_review()
    assert (r["total"], r["previous"]) == (3, 5)
    assert r["hardest_hour"] == 21
    assert r["top_trigger"] == "Bored"
    assert r["quietest_day"] == 6  # Sunday: zero, latest of the ties
    assert make_log(tmp_path, []).week_review() is None


def test_calmer_days_count_days_below_your_own_average(tmp_path):
    # 30-day window ending today (Sat 10 Oct): 3 urges on each of 5 busy days, 15 total -> average 0.5/day
    busy = [NOW - timedelta(days=d) for d in (20, 21, 22, 23, 24) for _ in range(3)]
    log = make_log(tmp_path, busy)
    r = log.calmer_days(30)
    assert r["calm"] == 25 and r["of"] == 30
    assert r["run"] == 20 and r["best_run"] == 20
    assert make_log(tmp_path, []).calmer_days(30) is None


def test_sync_merge_keeps_the_latest_edit_and_every_event():
    import sync
    a = {"id": "a", "t": 1, "u": 5, "intensity": 2}
    a_newer = {"id": "a", "t": 1, "u": 9, "intensity": 4}
    b = {"id": "b", "t": 2, "u": 1}
    merged = sync.merge([a, b], [a_newer])
    assert merged == [a_newer, b]
    assert sync.merge(merged, merged) == merged  # repeating a sync changes nothing


def test_pc_events_round_trip_through_the_shared_format(tmp_path):
    import sync
    log = EventLog(tmp_path / "events.json", now=lambda: NOW)
    e = log.record_press(3)
    log.record_choice(e, "walk")
    shared = log.shared()
    assert shared[0]["t"] == int(NOW.timestamp() * 1000) and shared[0]["choices"] == ["walk"]
    other = EventLog(tmp_path / "other.json", now=lambda: NOW)
    phone = dict(shared[0], id="phone1", u=shared[0]["u"] + 1, triggers=["Bored"])
    assert other.apply_shared(sync.merge(shared, [phone]))
    assert {x["id"] for x in other.events} == {e["id"], "phone1"}
    assert sync.from_shared(phone)["ts"] == NOW.isoformat(timespec="seconds")


def test_blocker_never_closes_protected_apps():
    from blocker import AppBlocker
    b = AppBlocker()
    b.start(["Steam", "explorer.exe", "chrome.exe"], 60)
    assert b.names == ["steam.exe", "chrome.exe"] and b.active()
    b.stop()
    assert not b.active()


def test_cluster_minutes_ladder():
    from urge_log import cluster_minutes
    assert [cluster_minutes(3, n) for n in range(4)] == [3, 5, 10, 10]
    assert cluster_minutes(8, 1) == 8      # your own length wins when it's already longer
    assert cluster_minutes(25, 2) == 25


def test_recent_locks_counts_only_locks_in_the_window(tmp_path):
    log = make_log(tmp_path, [NOW - timedelta(minutes=10), NOW - timedelta(minutes=40)])
    log.record_logged(2)
    assert log.recent_locks() == 1


def bored(log, t, *choices):
    """Append a Bored press the way record_bored + record_choice would store it."""
    log.events.append({"ts": t.isoformat(timespec="seconds"), "kind": "bored", "minutes": 0, "choices": list(choices),
                       "intensity_start": None, "intensity": None, "triggers": []})


def test_bored_presses_stay_out_of_every_urge_stat(tmp_path):
    log = make_log(tmp_path, [NOW - timedelta(hours=1), NOW - timedelta(days=1)])
    log.record_choice(log.events[0], "walk")
    bored(log, NOW - timedelta(minutes=30), "sudoku")
    bored(log, NOW - timedelta(hours=2))
    for d in range(1, 6):                       # 9 PM five days running: would be a "hard hour" if it counted
        bored(log, NOW.replace(hour=21) - timedelta(days=d), "walk")
    for d in range(3):                          # last week (Mon 28 Sep .. Sun 4 Oct) has only Bored presses
        bored(log, datetime(2026, 9, 29, 21) + timedelta(days=d))
    assert len(log.urges()) == 2 and all(e["kind"] != "bored" for e in log.urges())
    assert log.today() == 1 and log.this_week() == 2
    assert log.since_last() == 3600 and log.longest_gap() == 23 * 3600
    assert log.per_day(2) == [((NOW - timedelta(days=1)).date(), 1), (NOW.date(), 1)]
    assert log.by_hour()[14] == 1 and sum(log.by_hour()) == 1
    assert sum(map(sum, log.heat(30))) == 2
    assert log.risky_hours() == set()
    assert log.recent_locks() == 0
    assert log.choice_counts()["sudoku"] == 0 and log.choice_counts()["walk"] == 1
    assert log.relief_by_choice() == {} and log.trigger_counts() == []
    assert log.calmer_days(30)["calm"] == 28
    assert log.week_review() is None


def test_bored_counts_picks_and_heat(tmp_path):
    log = make_log(tmp_path, [])
    bored(log, NOW.replace(hour=10, minute=0), "sudoku")
    bored(log, NOW.replace(hour=13, minute=30), "sudoku")
    bored(log, NOW.replace(hour=15, minute=0))                         # dismissed without picking
    bored(log, NOW.replace(hour=20) - timedelta(days=1), "write")      # yesterday evening: after "by now"
    bored(log, datetime(2026, 10, 6, 9), "Juggle")                     # Tuesday this week, your own idea
    bored(log, datetime(2026, 9, 30, 21), "water")                     # last week
    assert log.today(bored=True) == 3 and log.yesterday_by_now(bored=True) == 0
    assert log.this_week(bored=True) == 5 and log.last_week_by_now(bored=True) == 1
    assert log.per_day(2, bored=True) == [((NOW - timedelta(days=1)).date(), 1), (NOW.date(), 3)]
    heat = log.heat(30, bored=True)
    assert heat[NOW.weekday()][13] == 1 and sum(map(sum, heat)) == 6
    assert log.bored_choice_counts() == [("sudoku", 2), ("Juggle", 1), ("none", 1), ("water", 1), ("write", 1)]
    assert log.bored_choice_counts(days=1) == [("sudoku", 2), ("none", 1)]
    assert log.today() == 0 and log.this_week() == 0                   # none of it is an urge


def test_bored_then_urge_within_the_hour(tmp_path):
    urges = [NOW.replace(hour=9, minute=30), NOW.replace(hour=10, minute=40), NOW.replace(hour=14, minute=30),
             NOW - timedelta(days=40) + timedelta(minutes=10)]
    log = make_log(tmp_path, urges)
    bored(log, NOW.replace(hour=10, minute=0))      # urge 40 minutes later: counts
    bored(log, NOW.replace(hour=13, minute=0))      # urge 90 minutes later: doesn't
    bored(log, NOW.replace(hour=15, minute=0))      # nothing after it
    bored(log, NOW - timedelta(days=40))            # outside the 30-day window
    assert log.bored_then_urge() == (1, 3)
    assert log.bored_then_urge(minutes=120) == (2, 3)
    assert make_log(tmp_path, []).bored_then_urge() == (0, 0)


def test_bored_round_trips_through_sync(tmp_path):
    import sync
    from urge_log import is_urge
    log = EventLog(tmp_path / "events.json", now=lambda: NOW)
    e = log.record_bored()
    log.record_choice(e, "stretch")
    assert e["kind"] == "bored" and e["minutes"] == 0 and not is_urge(e)
    shared = log.shared()
    assert shared[0]["kind"] == "bored" and shared[0]["choices"] == ["stretch"]
    assert sync.from_shared(shared[0])["kind"] == "bored"
    other = EventLog(tmp_path / "other.json", now=lambda: NOW)
    assert other.apply_shared(sync.merge(shared, []))
    assert other.today() == 0 and other.today(bored=True) == 1
    assert other.bored_choice_counts() == [("stretch", 1)]


def test_activity_fields_round_trip_through_sync_and_stay_off_urges(tmp_path):
    import sync
    log = EventLog(tmp_path / "events.json", now=lambda: NOW)
    urge = log.record_press(3)
    e = log.record_bored()
    log.record_choice(e, "read")
    log.record_outcome(e, True, 601.4)
    log.record_note(e, "  the river chapter  ")
    log.record_amount(e, 12)
    assert (e["done"], e["seconds"], e["note"], e["amount"]) == (True, 601, "the river chapter", 12)
    shared = {s["id"]: s for s in log.shared()}
    assert {k: shared[e["id"]][k] for k in ("done", "seconds", "note", "amount")} == {"done": True, "seconds": 601, "note": "the river chapter", "amount": 12}
    assert not {"done", "seconds", "note", "amount"} & set(shared[urge["id"]])   # an urge never carries them
    other = EventLog(tmp_path / "other.json", now=lambda: NOW)
    assert other.apply_shared(sync.merge(log.shared(), []))
    got = next(x for x in other.events if x["id"] == e["id"])
    assert (got["done"], got["seconds"], got["note"], got["amount"]) == (True, 601, "the river chapter", 12)
    plain = sync.from_shared({"id": "p", "t": 0, "u": 0, "kind": "bored", "choices": ["water"]})
    assert plain["done"] is None and plain["note"] is None                      # older copies have none of them
    assert sync.merge([dict(shared[e["id"]], mystery=1)], [])[0]["mystery"] == 1  # unknown fields pass through untouched


def test_deleting_a_note_clears_it_and_bumps_u(tmp_path):
    log = EventLog(tmp_path / "events.json", now=lambda: NOW)
    e = log.record_bored()
    log.record_choice(e, "write")
    log.record_note(e, "call mum back")
    before = e["u"]
    assert [x["note"] for _, x in log.bored_notes()] == ["call mum back"]
    e["u"] = before - 10  # make the bump visible even inside one millisecond
    log.record_note(e, "")
    assert e["note"] is None and e["u"] > before - 10
    assert log.bored_notes() == []
    assert "note" not in log.shared()[0]


def test_notes_newest_first_and_last_practice_note(tmp_path):
    log = make_log(tmp_path, [])
    bored(log, NOW - timedelta(days=2), "practice")
    log.events[-1]["note"] = "scales"
    bored(log, NOW - timedelta(hours=3), "write")
    log.events[-1]["note"] = "too many tabs open"
    bored(log, NOW - timedelta(hours=1), "practice")
    log.events[-1]["note"] = "the Bach prelude"
    bored(log, NOW - timedelta(minutes=5), "water")               # no note
    assert [e["note"] for _, e in log.bored_notes()] == ["the Bach prelude", "too many tabs open", "scales"]
    assert log.last_note("practice") == "the Bach prelude"
    assert log.last_note("read") == ""


def test_finished_of_picked_minutes_and_idea_rows(tmp_path):
    log = make_log(tmp_path, [])
    bored(log, NOW - timedelta(hours=5), "write"); log.events[-1].update(done=True, seconds=60)
    bored(log, NOW - timedelta(hours=4), "stretch"); log.events[-1].update(done=False, seconds=30)
    bored(log, NOW - timedelta(hours=3), "read"); log.events[-1].update(done=True, seconds=600)
    bored(log, NOW - timedelta(hours=2), "read")                   # closed the window mid-way: nothing recorded
    bored(log, NOW - timedelta(hours=1), "sudoku")                 # a jump: never finished, never counted
    bored(log, NOW - timedelta(minutes=30))                        # dismissed without picking
    bored(log, NOW - timedelta(days=40), "write"); log.events[-1].update(done=True, seconds=120)   # outside 30 days
    assert log.bored_finished(30) == (2, 4)
    assert log.bored_seconds(30) == 690
    assert log.bored_seconds(None) == 810
    assert log.bored_idea_rows(30) == [("read", 2, 1), ("none", 1, 0), ("stretch", 1, 0), ("sudoku", 1, 0), ("write", 1, 1)]
    assert log.today() == 0                                        # none of it is an urge


def test_water_glasses_today(tmp_path):
    log = make_log(tmp_path, [])
    bored(log, NOW.replace(hour=9), "water"); log.events[-1].update(done=True, seconds=20)
    bored(log, NOW.replace(hour=12), "water"); log.events[-1].update(done=True, seconds=15)
    bored(log, NOW.replace(hour=14), "water")                      # picked, never tapped "I drank it"
    bored(log, NOW.replace(hour=14, minute=30), "stretch"); log.events[-1].update(done=True, seconds=120)
    bored(log, NOW.replace(hour=20) - timedelta(days=1), "water"); log.events[-1].update(done=True, seconds=20)
    assert log.glasses_today() == 2


def test_stretch_schedule():
    from urge_log import STRETCHES, activity_seconds, stretch_at
    assert len(STRETCHES) == 6 and activity_seconds("stretch") == 120
    assert stretch_at(0) == (0, "Neck rolls", "Shoulder rolls", 20)
    assert stretch_at(19.5)[0] == 0 and stretch_at(19.5)[3] == 0.5
    assert stretch_at(20)[:3] == (1, "Shoulder rolls", "Reach up tall")
    assert stretch_at(100) == (5, "Chest opener", None, 20)
    assert stretch_at(120) is None and stretch_at(-1) is None
    assert activity_seconds("outside") == 300 and activity_seconds("read") == 600 and activity_seconds("Juggle") == 300


def test_countdown_reads_the_clock_not_the_ticks():
    from urge_log import Countdown, clock_text
    clock = [1000.0]
    c = Countdown(300, now=lambda: clock[0])
    clock[0] += 125
    assert c.remaining() == 175 and c.elapsed() == 125
    c.pause()
    clock[0] += 60                                   # a minute goes by while paused: nothing moves
    assert c.remaining() == 175 and c.paused
    c.resume()
    clock[0] += 10
    assert c.remaining() == 165 and not c.paused
    clock[0] += 1000                                 # the window sat in the background past the end
    assert c.remaining() == 0 and c.elapsed() == 1135   # 125 + 10 + 1000: the paused minute is not in it
    assert clock_text(175) == "2:55" and clock_text(0.2) == "0:01" and clock_text(0) == "0:00"


def test_finish_lines():
    from urge_log import DEFAULT_FINISH_LINES, finish_line
    assert finish_line("stretch") == "Looser already? Two minutes well spent."
    assert finish_line("Juggle", rng=random.Random(2)) in DEFAULT_FINISH_LINES


def test_pick_ideas_gives_three_different_ones_and_shuffles():
    from urge_log import BORED_IDEAS, pick_ideas
    ideas = [text for _, text in BORED_IDEAS]
    rng = random.Random(1)
    first = pick_ideas(ideas, rng=rng)
    assert len(first) == 3 and len(set(first)) == 3 and set(first) <= set(ideas)
    second = pick_ideas(ideas, avoid=first, rng=rng)
    assert len(second) == 3 and not set(second) & set(first)
    assert len({tuple(sorted(pick_ideas(ideas, rng=random.Random(s)))) for s in range(12)}) > 1
    assert len(pick_ideas(ideas[:4], avoid=first, rng=rng)) == 3          # too few to avoid: show any three
    assert pick_ideas(["a", "b"]) in (["a", "b"], ["b", "a"])
    assert sorted(pick_ideas(["a", "a", "b"])) == ["a", "b"]


def test_bored_ideas_from_settings_and_their_keys():
    from urge_log import BORED_IDEAS, bored_ideas, bored_key, bored_name
    assert bored_ideas({"bored_ideas": []}) == [text for _, text in BORED_IDEAS]
    assert bored_ideas({"bored_ideas": [" Juggle ", "", "Play Sudoku"]}) == ["Juggle", "Play Sudoku"]
    assert bored_key("Play Sudoku") == "sudoku" and bored_key("  put music ON ") == "music"
    assert bored_key("Juggle") == "Juggle"
    assert bored_name("none") == "Just logged it" and bored_name("sudoku") == "Play Sudoku" and bored_name("Juggle") == "Juggle"


def test_push_ignores_bored_presses():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "push"))
    from zoneinfo import ZoneInfo

    import headsup_push as hp
    tz = ZoneInfo("America/Toronto")
    now = datetime(2026, 10, 10, 20, 40, tzinfo=tz)
    push = {"enabled": True, "subscription": {"endpoint": "x"}, "plan": ""}
    nine_pm = [{"t": int((now.replace(hour=21) - timedelta(days=d)).timestamp() * 1000)} for d in range(1, 6)]
    bored_nine = [dict(e, kind="bored") for e in nine_pm]
    assert hp.message(bored_nine, push, now) is None                            # boredom isn't a hard hour
    just_bored = nine_pm + [{"t": int((now - timedelta(minutes=5)).timestamp() * 1000), "kind": "bored"}]
    assert hp.message(just_bored, push, now) is not None                        # a Bored press doesn't silence it


def test_push_message_only_before_a_hard_hour():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "push"))
    from zoneinfo import ZoneInfo

    import headsup_push as hp
    tz = ZoneInfo("America/Toronto")
    now = datetime(2026, 10, 10, 20, 40, tzinfo=tz)
    nine_pm = [{"t": int((now.replace(hour=21) - timedelta(days=d)).timestamp() * 1000)} for d in range(1, 6)]
    push = {"enabled": True, "subscription": {"endpoint": "x"}, "plan": "Make tea."}
    title, body = hp.message(nine_pm, push, now)
    assert body == "9 PM is usually one of your harder hours. Your plan: Make tea."
    assert hp.message(nine_pm, push, now.replace(hour=18)) is None             # 7 PM isn't hard
    assert hp.message(nine_pm, dict(push, enabled=False), now) is None
    just_now = nine_pm + [{"t": int((now - timedelta(minutes=5)).timestamp() * 1000)}]
    assert hp.message(just_now, push, now) is None                             # you just logged one


def test_emergency_exit_rides_on_the_urge_only_when_set(tmp_path):
    import sync
    log = EventLog(tmp_path / "events.json", now=lambda: NOW)
    cut, plain = log.record_press(3), log.record_press(3)
    log.record_emergency_exit(cut)
    assert cut["emergency_exit"] is True and "emergency_exit" not in plain
    shared = {s["id"]: s for s in log.shared()}
    assert shared[cut["id"]]["emergency_exit"] is True and "emergency_exit" not in shared[plain["id"]]
    assert sync.from_shared(shared[cut["id"]])["emergency_exit"] is True
    assert sync.from_shared(shared[plain["id"]])["emergency_exit"] is None
    assert sync.merge([shared[cut["id"]]], [])[0]["emergency_exit"] is True
    assert EventLog(tmp_path / "events.json", now=lambda: NOW).events[0]["emergency_exit"] is True
