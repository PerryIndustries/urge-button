import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sudoku  # noqa: E402
import sync  # noqa: E402
from sudoku import DIFFICULTIES, Game, SudokuLog  # noqa: E402

NOW = datetime(2026, 10, 10, 15, 30)  # a Saturday afternoon
NOW_MS = int(NOW.timestamp() * 1000)


def ms(dt):
    return int(dt.timestamp() * 1000)


def new_game(seed=1, diff="easy", **kw):
    return Game.new(diff, started=NOW_MS, rng=random.Random(seed), **kw)


def open_cell(g):
    return next(p for p in range(81) if not g.puz[p])


# -- puzzles


def test_every_difficulty_has_one_answer_and_about_the_right_number_of_clues():
    for key, (_, target) in DIFFICULTIES.items():
        for seed in range(3):
            puz, sol = sudoku.generate(key, random.Random(seed))
            clues = sum(1 for v in puz if v)
            assert target <= clues <= target + 3, (key, clues)
            assert sudoku.count_solutions(puz, 2) == 1
            assert all(not v or v == s for v, s in zip(puz, sol))
            assert sudoku.is_valid_solution([sol[i:i + 9] for i in range(0, 81, 9)])


def test_count_solutions_sees_a_second_answer():
    puz, sol = sudoku.generate("easy", random.Random(5))
    # Blank out the whole first box: at least two ways to fill it are left
    for p in sudoku.UNITS[18]:
        puz[p] = 0
    assert sudoku.count_solutions(puz, 2) == 2
    assert sudoku.count_solutions([0] * 81, 3) == 3


def test_make_puzzle_keeps_the_grid_shape():
    puzzle, solution = sudoku.make_puzzle(random.Random(3), "medium")
    assert len(puzzle) == 9 and all(len(r) == 9 for r in puzzle)
    assert sum(1 for r in puzzle for v in r if v) == 32


# -- play


def test_wrong_digit_counts_a_mistake_but_stays_and_right_digit_does_not():
    g = new_game()
    p = open_cell(g)
    wrong = next(n for n in range(1, 10) if n != g.sol[p])
    assert g.place(p, wrong) and g.mistakes == 1 and g.vals[p] == wrong
    assert g.place(p, g.sol[p]) and g.mistakes == 1 and g.vals[p] == g.sol[p]
    assert g.moves == 2


def test_clues_and_correct_digits_cannot_be_changed_or_erased():
    g = new_game()
    given = next(p for p in range(81) if g.puz[p])
    assert not g.place(given, 1) and not g.erase(given)
    p = open_cell(g)
    g.place(p, g.sol[p])
    assert not g.erase(p) and not g.place(p, 1 if g.sol[p] != 1 else 2)
    assert g.vals[p] == g.sol[p]


def test_notes_toggle_and_a_correct_digit_clears_them_from_its_peers():
    g = new_game()
    p = open_cell(g)
    n = g.sol[p]
    peer = next(q for q in sudoku.PEERS[p] if not g.puz[q] and g.vals[q] == 0)
    far = next(q for q in range(81) if not g.puz[q] and q not in sudoku.PEERS[p] and q != p)
    assert g.place(peer, n, notes=True) and g.notes[peer] == 1 << n
    assert g.place(peer, 5, notes=True) and g.notes[peer] == (1 << n) | (1 << 5)
    assert g.place(peer, 5, notes=True) and g.notes[peer] == 1 << n   # toggles off again
    g.place(far, n, notes=True)
    assert g.place(p, n)
    assert g.notes[peer] == 0 and g.notes[far] == 1 << n


def test_wrong_digit_leaves_peer_notes_alone():
    g = new_game()
    p = open_cell(g)
    wrong = next(n for n in range(1, 10) if n != g.sol[p])
    peer = next(q for q in sudoku.PEERS[p] if not g.puz[q])
    g.place(peer, wrong, notes=True)
    g.place(p, wrong)
    assert g.notes[peer] == 1 << wrong


def test_undo_restores_the_cell_and_the_notes_it_cleared():
    g = new_game()
    p = open_cell(g)
    n = g.sol[p]
    peer = next(q for q in sudoku.PEERS[p] if not g.puz[q])
    g.place(peer, n, notes=True)
    g.place(p, n)
    assert g.undo_move()
    assert g.vals[p] == 0 and g.notes[peer] == 1 << n
    assert g.undo_move() and g.notes[peer] == 0
    assert not g.undo_move()


def test_erase_clears_a_wrong_digit_or_notes_and_can_be_undone():
    g = new_game()
    p = open_cell(g)
    assert not g.erase(p)  # nothing there
    wrong = next(n for n in range(1, 10) if n != g.sol[p])
    g.place(p, wrong)
    assert g.erase(p) and g.vals[p] == 0
    assert g.undo_move() and g.vals[p] == wrong


def test_hint_fills_the_selected_cell_or_the_most_filled_in_one():
    g = new_game()
    p = open_cell(g)
    assert g.hint(p) == p and g.vals[p] == g.sol[p] and g.hints == 1
    # with a right digit selected the hint goes elsewhere: to the open cell with the fullest neighbourhood
    q = g.hint(p)
    assert q != p and g.vals[q] == g.sol[q]
    fullness = {c: sum(1 for r in sudoku.PEERS[c] if g.vals[r]) for c in range(81) if g.vals[c] != g.sol[c]}
    before = sum(1 for r in sudoku.PEERS[q] if g.vals[r])
    assert all(before >= f for f in fullness.values())


def test_remaining_counts_only_correct_placements_and_units_flash_when_finished():
    g = new_game()
    rem = g.remaining()
    assert all(rem[n] == 9 - sum(1 for p in range(81) if g.puz[p] == n) for n in range(1, 10))
    row = [p for p in range(9) if not g.puz[p]]
    for p in row[:-1]:
        g.place(p, g.sol[p])
    last = row[-1]
    wrong = next(n for n in range(1, 10) if n != g.sol[last])
    g.place(last, wrong)
    assert g.remaining()[wrong] == 9 - sum(1 for p in range(81) if g.vals[p] == wrong and g.sol[p] == wrong)
    assert not (g.completed_units(last) & set(range(9)))
    g.place(last, g.sol[last])
    assert set(range(9)) <= g.completed_units(last)


def test_solving_the_last_cell_finishes_the_game_in_the_log(tmp_path):
    log = SudokuLog(tmp_path / "sudoku.json", now_ms=lambda: NOW_MS)
    g = log.start("easy", rng=random.Random(2))
    for p in range(81):
        if not g.puz[p]:
            g.place(p, g.sol[p])
            log.changed()
    assert g.done and log.games[-1]["solved"] and log.games[-1]["id"] == g.id
    assert log.games[-1]["mistakes"] == 0 and log.games[-1]["from_urge"] is False
    again = SudokuLog(tmp_path / "sudoku.json")
    assert again.current.done and again.playable() is None and len(again.games) == 1


def test_starting_over_records_a_touched_game_as_unfinished(tmp_path):
    log = SudokuLog(tmp_path / "sudoku.json", now_ms=lambda: NOW_MS)
    notes = []
    log.on_change = notes.append
    untouched = log.start("hard", rng=random.Random(1))
    log.start("easy")                          # no moves: nothing to record
    g = log.start("medium", from_urge=True)
    g.place(open_cell(g), 1, notes=True)
    log.changed()
    log.start("expert")
    assert [x["id"] for x in log.games] == [g.id] and untouched.id not in {x["id"] for x in log.games}
    assert log.games[0]["solved"] is False and log.games[0]["from_urge"] is True
    assert log.difficulty == "expert" and notes == ["now", "now", "now", "soon", "now"]


def test_saved_game_round_trips(tmp_path):
    log = SudokuLog(tmp_path / "sudoku.json", now_ms=lambda: NOW_MS)
    g = log.start("hard", rng=random.Random(4))
    p = open_cell(g)
    g.place(p, 3, notes=True)
    g.elapsed = 61.4
    log.changed()
    again = SudokuLog(tmp_path / "sudoku.json").current
    assert again.to_dict() == g.to_dict()
    assert again.undo == [[[p, 0, 0]]] and again.elapsed == 61.4


# -- stats


def rec(days_ago, diff="easy", seconds=300, solved=True, mistakes=0, hints=0, hour=12):
    t = ms((NOW - timedelta(days=days_ago)).replace(hour=hour))
    return {"id": f"{days_ago}-{diff}-{seconds}", "diff": diff, "started": t - seconds * 1000, "t": t,
            "seconds": seconds, "mistakes": mistakes, "hints": hints, "solved": solved, "from_urge": False, "u": t}


def test_stats_best_average_perfect_and_week():
    games = [rec(0, "easy", 200), rec(1, "easy", 400, mistakes=2), rec(2, "easy", 300, hints=1),
             rec(3, "hard", 900), rec(4, "hard", 1000, solved=False), rec(20, "medium", 500)]
    s = sudoku.stats(games, NOW)
    assert s["solved"] == 5 and s["started"] == 6
    assert s["week"] == 4                       # Monday the 5th onwards: 3 easy + 1 hard
    easy = s["by_difficulty"]["easy"]
    assert easy["solved"] == 3 and easy["best"] == 200 and easy["average"] == 300 and easy["perfect"] == 1
    hard = s["by_difficulty"]["hard"]
    assert hard == {"solved": 1, "started": 2, "best": 900, "average": 900, "perfect": 1}
    assert s["by_difficulty"]["expert"]["best"] is None
    assert [g["t"] for g in s["recent"]] == sorted((g["t"] for g in games), reverse=True)
    assert sudoku.best_time(games, "easy") == 200 and sudoku.best_time(games, "easy", except_id=games[0]["id"]) == 300
    assert sudoku.best_time(games, "expert") is None


def test_streak_counts_days_in_a_row_ending_today_or_yesterday():
    today = NOW.date()
    assert sudoku.streak([rec(0), rec(1), rec(2), rec(4)], today) == 3
    assert sudoku.streak([rec(1), rec(2)], today) == 2            # today isn't over yet
    assert sudoku.streak([rec(2), rec(3)], today) == 0
    assert sudoku.streak([rec(0, solved=False), rec(1)], today) == 1
    assert sudoku.streak([], today) == 0


def test_format_clock():
    assert sudoku.format_clock(5) == "0:05"
    assert sudoku.format_clock(754) == "12:34"
    assert sudoku.format_clock(3661) == "1:01:01"


# -- sync


def test_sudoku_merge_unions_games_and_takes_the_newer_current():
    a = {"id": "a", "t": 1, "u": 5, "solved": False}
    a_newer = dict(a, u=9, solved=True)
    b = {"id": "b", "t": 2, "u": 1}
    old_cur = {"id": "g1", "u": 10, "vals": [0] * 81}
    new_cur = {"id": "g2", "u": 20, "vals": [1] * 81}
    merged = sync.merge_sudoku({"games": [a, b], "current": old_cur}, {"games": [a_newer], "current": new_cur})
    assert merged == {"version": 1, "games": [a_newer, b], "current": new_cur}
    assert sync.merge_sudoku(merged, None) == merged                       # repeating changes nothing
    assert sync.merge_sudoku(None, {"games": [a], "current": None})["current"] is None
    assert sync.merge_sudoku({"current": old_cur}, {"current": None})["current"] == old_cur
    assert sync.merge_sudoku({"current": None}, {"current": old_cur})["current"] == old_cur
    tie = sync.merge_sudoku({"current": old_cur}, {"current": dict(old_cur, vals=[2] * 81)})
    assert tie["current"] is old_cur                                       # the repo's copy wins a tie


class FakeRemote:
    def __init__(self, doc=None):
        self.doc, self.sha, self.writes = doc, "s1" if doc else None, 0

    def read_json(self):
        return self.doc, self.sha

    def write_json(self, data, sha):
        self.doc, self.writes = data, self.writes + 1
        return True


def test_sync_sudoku_writes_only_when_this_side_adds_something(tmp_path):
    log = SudokuLog(tmp_path / "sudoku.json", now_ms=lambda: NOW_MS)
    remote = FakeRemote()
    assert sync.sync_sudoku(log.shared(), remote) == {"version": 1, "games": [], "current": None}
    assert remote.writes == 0                                              # nothing to say yet: no empty file
    g = log.start("easy", rng=random.Random(1))
    merged = sync.sync_sudoku(log.shared(), remote)
    assert remote.writes == 1 and merged["current"]["id"] == g.id
    assert sync.sync_sudoku(log.shared(), remote) == merged and remote.writes == 1


def test_apply_shared_takes_the_newer_game_and_keeps_local_progress(tmp_path):
    clock = {"ms": NOW_MS}
    log = SudokuLog(tmp_path / "sudoku.json", now_ms=lambda: clock["ms"])
    mine = log.start("easy", rng=random.Random(1))
    mine.place(open_cell(mine), 4, notes=True)
    log.changed()
    # the phone started a different puzzle later
    clock["ms"] += 60_000
    theirs = Game.new("hard", started=clock["ms"], rng=random.Random(9))
    theirs.u = clock["ms"]
    notes = []
    log.on_change = notes.append
    assert log.apply_shared({"games": [], "current": theirs.to_dict()})
    assert log.current.id == theirs.id and log.difficulty == "hard"
    assert [x["id"] for x in log.games] == [mine.id] and log.games[0]["solved"] is False
    assert notes == ["now"]                                                # push the record back out
    # an older copy of the current game changes nothing
    stale = dict(theirs.to_dict(), u=theirs.u - 1, vals=[9] * 81)
    assert not log.apply_shared({"games": log.games, "current": stale})
    assert log.current.vals == theirs.vals
    # the same game with more progress on the other side replaces this copy
    ahead = dict(theirs.to_dict(), u=theirs.u + 5, moves=3)
    assert log.apply_shared({"games": log.games, "current": ahead})
    assert log.current.moves == 3 and len(log.games) == 1


def test_apply_shared_does_not_record_an_untouched_local_game(tmp_path):
    log = SudokuLog(tmp_path / "sudoku.json", now_ms=lambda: NOW_MS)
    log.start("easy", rng=random.Random(1))
    theirs = Game.new("medium", started=NOW_MS + 1, rng=random.Random(2))
    theirs.u = NOW_MS + 1
    assert log.apply_shared({"games": [], "current": theirs.to_dict()})
    assert log.games == [] and log.current.id == theirs.id
