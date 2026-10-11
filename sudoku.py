"""Sudoku: puzzles with exactly one answer, the rules of play, and the record of every game.

No UI in here, so all of it is testable. Cells are numbered 0-80, row by row.

A game in progress (the same shape is saved locally and shared through sudoku.json):
    {"id", "diff", "puz": [81 digits, 0 = blank], "sol": [81], "vals": [81], "notes": [81 bitmasks],
     "mistakes", "hints", "moves", "elapsed" (seconds), "started" (epoch ms), "from_urge",
     "done", "undo": [[[cell, old value, old notes], ...], ...], "u" (last change, epoch ms)}
A finished or abandoned game is kept as:
    {"id", "diff", "started", "t" (end, epoch ms), "seconds", "mistakes", "hints", "solved",
     "from_urge", "u"}
"""

import random
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from urge_log import APP_DIR, load_json, save_json

SUDOKU_PATH = APP_DIR / "sudoku.json"

# key -> (label, clues left in the puzzle)
DIFFICULTIES = {"easy": ("Easy", 38), "medium": ("Medium", 32), "hard": ("Hard", 27), "expert": ("Expert", 23)}
DEFAULT_DIFFICULTY = "easy"
UNDO_LIMIT = 120

ROW = [p // 9 for p in range(81)]
COL = [p % 9 for p in range(81)]
BOX = [(p // 27) * 3 + (p % 9) // 3 for p in range(81)]
UNITS = ([[r * 9 + c for c in range(9)] for r in range(9)]
         + [[r * 9 + c for r in range(9)] for c in range(9)]
         + [[p for p in range(81) if BOX[p] == b] for b in range(9)])
PEERS = [sorted({q for q in range(81) if q != p and (ROW[q] == ROW[p] or COL[q] == COL[p] or BOX[q] == BOX[p])})
         for p in range(81)]


def label(difficulty):
    return DIFFICULTIES.get(difficulty, (str(difficulty).title(),))[0]


# --------------------------------------------------------------------------- puzzles


def solved_grid(rng):
    grid = [[0] * 9 for _ in range(9)]

    def ok(r, c, n):
        if n in grid[r] or any(grid[i][c] == n for i in range(9)):
            return False
        br, bc = 3 * (r // 3), 3 * (c // 3)
        return all(grid[i][j] != n for i in range(br, br + 3) for j in range(bc, bc + 3))

    def fill(pos=0):
        if pos == 81:
            return True
        r, c = divmod(pos, 9)
        nums = list(range(1, 10))
        rng.shuffle(nums)
        for n in nums:
            if ok(r, c, n):
                grid[r][c] = n
                if fill(pos + 1):
                    return True
                grid[r][c] = 0
        return False

    fill()
    return grid


def count_solutions(grid, limit=2, forbid=None):
    """How many ways `grid` (81 digits, 0 = blank) can be completed, stopping once `limit` are found.

    Bitmasks per row/column/box and always-branch-on-the-fewest-candidates keep this fast enough to
    run dozens of times while a puzzle is made. `forbid=(cell, digit)` also rules that digit out of
    that cell, which is how generation asks "is there another answer without this clue?".
    """
    g = list(grid)
    rows, cols, boxes = [0] * 9, [0] * 9, [0] * 9
    for p, v in enumerate(g):
        if v:
            b = 1 << v
            rows[ROW[p]] |= b
            cols[COL[p]] |= b
            boxes[BOX[p]] |= b
    empties = [p for p in range(81) if not g[p]]
    fp, fmask = (forbid[0], ~(1 << forbid[1])) if forbid else (-1, 0)
    count = 0

    def search():
        nonlocal count
        best, best_mask, best_n = -1, 0, 10
        for p in empties:
            if g[p]:
                continue
            m = ~(rows[ROW[p]] | cols[COL[p]] | boxes[BOX[p]]) & 0x3FE
            if p == fp:
                m &= fmask
            n = m.bit_count()
            if n == 0:
                return
            if n < best_n:
                best, best_mask, best_n = p, m, n
                if n == 1:
                    break
        if best < 0:
            count += 1
            return
        r, c, bx = ROW[best], COL[best], BOX[best]
        m = best_mask
        while m:
            b = m & -m
            m ^= b
            g[best] = b.bit_length() - 1
            rows[r] |= b
            cols[c] |= b
            boxes[bx] |= b
            search()
            g[best] = 0
            rows[r] ^= b
            cols[c] ^= b
            boxes[bx] ^= b
            if count >= limit:
                return

    search()
    return count


def generate(difficulty=DEFAULT_DIFFICULTY, rng=None):
    """(puzzle, solution) as flat lists of 81. The puzzle has exactly one answer.

    Clues are removed in a shuffled order and a removal only stands if no other answer appears
    without it, down to the difficulty's clue count. Some grids can't get that low in one pass
    (Expert, mostly), so a few grids are tried and the sparsest one wins. Well under 0.1 s.
    """
    rng = rng or random.Random()
    target = DIFFICULTIES[difficulty][1]
    best = None
    for _ in range(4):
        sol = [v for row in solved_grid(rng) for v in row]
        puz = sol[:]
        clues = 81
        order = list(range(81))
        rng.shuffle(order)
        for p in order:
            if clues <= target:
                break
            v = puz[p]
            puz[p] = 0
            if count_solutions(puz, 1, forbid=(p, v)):
                puz[p] = v  # another answer sneaks in without this clue: keep it
            else:
                clues -= 1
        if best is None or clues < best[0]:
            best = (clues, puz, sol)
        if clues <= target:
            break
    return best[1], best[2]


def make_puzzle(rng=None, difficulty=DEFAULT_DIFFICULTY):
    """(puzzle, solution) as 9x9 grids - the older shape, kept for anything that still wants rows."""
    puz, sol = generate(difficulty, rng)
    return [puz[i:i + 9] for i in range(0, 81, 9)], [sol[i:i + 9] for i in range(0, 81, 9)]


def is_valid_solution(grid):
    full = list(range(1, 10))
    rows = all(sorted(r) == full for r in grid)
    cols = all(sorted(grid[i][c] for i in range(9)) == full for c in range(9))
    boxes = all(
        sorted(grid[br + i][bc + j] for i in range(3) for j in range(3)) == full
        for br in (0, 3, 6) for bc in (0, 3, 6)
    )
    return rows and cols and boxes


def check(entries, puzzle):
    """entries: {(r, c): int}. A cell is wrong if it clashes with a given or another entry.

    Checks against the rules rather than a stored answer, so it works for any valid grid.
    """
    grid = [row[:] for row in puzzle]
    for (r, c), v in entries.items():
        grid[r][c] = v
    wrong = set()
    for (r, c), v in entries.items():
        peers = {(r, j) for j in range(9)} | {(i, c) for i in range(9)}
        br, bc = 3 * (r // 3), 3 * (c // 3)
        peers |= {(br + i, bc + j) for i in range(3) for j in range(3)}
        peers.discard((r, c))
        if any(grid[pr][pc] == v for pr, pc in peers):
            wrong.add((r, c))
    empty = sum(1 for row in grid for v in row if v == 0)
    return wrong, empty


# --------------------------------------------------------------------------- a game


def now_ms():
    return int(time.time() * 1000)


class Game:
    """One puzzle being played, sudoku.com style: entries are checked against the answer as you go."""

    FIELDS = ("id", "diff", "puz", "sol", "vals", "notes", "mistakes", "hints", "moves", "elapsed",
              "started", "from_urge", "done", "undo", "u")

    def __init__(self, diff, puz, sol, started, from_urge=False, id=None):
        self.id = id or uuid.uuid4().hex
        self.diff = diff
        self.puz = list(puz)
        self.sol = list(sol)
        self.vals = list(puz)
        self.notes = [0] * 81          # bit n set = digit n pencilled in
        self.mistakes = 0
        self.hints = 0
        self.moves = 0                 # placements, erasures and hints (undo doesn't count)
        self.elapsed = 0.0             # seconds with the board actually in front of you
        self.started = started
        self.from_urge = bool(from_urge)
        self.done = False
        self.undo = []                 # each entry: the cells one move changed, as [cell, old value, old notes]
        self.u = started

    @classmethod
    def new(cls, difficulty=DEFAULT_DIFFICULTY, started=None, rng=None, from_urge=False):
        puz, sol = generate(difficulty, rng)
        return cls(difficulty, puz, sol, started if started is not None else now_ms(), from_urge)

    @classmethod
    def from_dict(cls, d):
        """A saved game, or None when the data isn't one."""
        try:
            if not (len(d["puz"]) == len(d["sol"]) == len(d["vals"]) == 81):
                return None
            g = cls(d.get("diff") or DEFAULT_DIFFICULTY, d["puz"], d["sol"], int(d.get("started") or 0),
                    d.get("from_urge", False), d.get("id"))
            g.vals = [int(v) for v in d["vals"]]
            notes = d.get("notes") or []
            g.notes = [int(n) for n in notes] if len(notes) == 81 else [0] * 81
            g.mistakes = int(d.get("mistakes") or 0)
            g.hints = int(d.get("hints") or 0)
            g.moves = int(d.get("moves") or 0)
            g.elapsed = float(d.get("elapsed") or 0)
            g.done = bool(d.get("done"))
            g.undo = [[list(map(int, cell)) for cell in step] for step in (d.get("undo") or [])]
            g.u = int(d.get("u") or g.started)
        except (KeyError, TypeError, ValueError):
            return None
        return g

    def to_dict(self):
        return {f: getattr(self, f) for f in self.FIELDS}

    # -- what's where

    def solved(self):
        return self.vals == self.sol

    def can_edit(self, p):
        """Clues and digits already right stay put."""
        return not self.puz[p] and self.vals[p] != self.sol[p]

    def remaining(self):
        """{digit: how many of it are still to place} - counts only digits that are in the right cell."""
        placed = [0] * 10
        for p, v in enumerate(self.vals):
            if v and v == self.sol[p]:
                placed[v] += 1
        return {n: 9 - placed[n] for n in range(1, 10)}

    def completed_units(self, p):
        """Cells of every row, column or box through `p` that is now completely right (to flash)."""
        out = set()
        for unit in (UNITS[ROW[p]], UNITS[9 + COL[p]], UNITS[18 + BOX[p]]):
            if all(self.vals[q] == self.sol[q] for q in unit):
                out.update(unit)
        return out

    # -- moves (each returns True when something changed)

    def _snapshot(self, p):
        return [p, self.vals[p], self.notes[p]]

    def _push_undo(self, cells):
        self.undo.append(cells)
        del self.undo[:-UNDO_LIMIT]

    def _clear_peer_notes(self, p, n, changed):
        for q in PEERS[p]:
            if self.notes[q] & (1 << n):
                changed.append(self._snapshot(q))
                self.notes[q] &= ~(1 << n)

    def place(self, p, n, notes=False):
        """Put digit n in cell p, or toggle it as a note. A wrong digit counts as a mistake but stays
        on the board in red; a right one clears that digit from the notes around it."""
        if self.done or not self.can_edit(p) or not 1 <= n <= 9:
            return False
        if notes:
            if self.vals[p]:
                return False
            self._push_undo([self._snapshot(p)])
            self.notes[p] ^= 1 << n
        else:
            if self.vals[p] == n:
                return False
            changed = [self._snapshot(p)]
            self.vals[p] = n
            self.notes[p] = 0
            if n == self.sol[p]:
                self._clear_peer_notes(p, n, changed)
            else:
                self.mistakes += 1
            self._push_undo(changed)
        self.moves += 1
        return True

    def erase(self, p):
        if self.done or not self.can_edit(p) or not (self.vals[p] or self.notes[p]):
            return False
        self._push_undo([self._snapshot(p)])
        self.vals[p] = 0
        self.notes[p] = 0
        self.moves += 1
        return True

    def undo_move(self):
        if self.done or not self.undo:
            return False
        for p, v, n in self.undo.pop():
            self.vals[p] = v
            self.notes[p] = n
        return True

    def hint_cell(self, p=None):
        """The cell a hint would fill: the selected one if it's open, else the open cell with the
        most of its row, column and box already filled."""
        if p is not None and self.vals[p] != self.sol[p]:
            return p
        open_cells = [q for q in range(81) if self.vals[q] != self.sol[q]]
        if not open_cells:
            return None
        return max(open_cells, key=lambda q: (sum(1 for r in PEERS[q] if self.vals[r]), -q))

    def hint(self, p=None):
        """Fill one cell with its answer. Returns the cell, or None when the puzzle is done."""
        if self.done:
            return None
        p = self.hint_cell(p)
        if p is None:
            return None
        changed = [self._snapshot(p)]
        n = self.sol[p]
        self.vals[p] = n
        self.notes[p] = 0
        self._clear_peer_notes(p, n, changed)
        self._push_undo(changed)
        self.hints += 1
        self.moves += 1
        return p

    def summary(self, solved, ended):
        return {"id": self.id, "diff": self.diff, "started": self.started, "t": ended,
                "seconds": int(round(self.elapsed)), "mistakes": self.mistakes, "hints": self.hints,
                "solved": bool(solved), "from_urge": self.from_urge, "u": ended}


# --------------------------------------------------------------------------- stats


def format_clock(seconds):
    s = int(max(0, seconds))
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _day(ms):
    return datetime.fromtimestamp(ms / 1000).date()


def streak(games, today):
    """Days in a row with at least one solve, ending today or yesterday."""
    days = {_day(g["t"]) for g in games if g.get("solved")}
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


def stats(games, now):
    """Everything the stats panel shows. `games` are the records; `now` a local datetime."""
    games = [g for g in games if isinstance(g, dict) and isinstance(g.get("t"), (int, float))]
    solved = [g for g in games if g.get("solved")]
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week = sum(1 for g in solved if datetime.fromtimestamp(g["t"] / 1000) >= monday)
    by_diff = {}
    for key in DIFFICULTIES:
        s = [g for g in solved if g.get("diff") == key]
        times = [g.get("seconds", 0) for g in s]
        by_diff[key] = {
            "solved": len(s),
            "started": sum(1 for g in games if g.get("diff") == key),
            "best": min(times) if times else None,
            "average": sum(times) / len(times) if times else None,
            "perfect": sum(1 for g in s if not g.get("mistakes") and not g.get("hints")),
        }
    return {
        "solved": len(solved),
        "started": len(games),
        "week": week,
        "streak": streak(games, now.date()),
        "by_difficulty": by_diff,
        "recent": sorted(games, key=lambda g: g["t"], reverse=True)[:10],
    }


def best_time(games, difficulty, except_id=None):
    """Fastest solve at a difficulty in seconds, or None. `except_id` leaves one game out (the one just finished)."""
    times = [g.get("seconds", 0) for g in games
             if g.get("solved") and g.get("diff") == difficulty and g.get("id") != except_id]
    return min(times) if times else None


# --------------------------------------------------------------------------- storage


class SudokuLog:
    """sudoku.json next to events.json: every finished or abandoned game, plus the puzzle in progress.

    `on_change(notify)` is called after a save that should reach the other device: "soon" after a
    move, "now" when a game starts or ends. The clock ticking saves quietly, without it.
    """

    def __init__(self, path=SUDOKU_PATH, now_ms=now_ms):
        self.path = Path(path)
        self.now_ms = now_ms
        self.on_change = None
        data = load_json(self.path, {})
        if not isinstance(data, dict):
            data = {}
        self.games = sorted((g for g in data.get("games") or [] if isinstance(g, dict) and g.get("id")),
                            key=lambda g: g.get("t", 0))
        self.current = Game.from_dict(data["current"]) if isinstance(data.get("current"), dict) else None
        self.difficulty = data.get("diff") or (self.current.diff if self.current else DEFAULT_DIFFICULTY)
        if self.difficulty not in DIFFICULTIES:
            self.difficulty = DEFAULT_DIFFICULTY

    def save(self, notify=None):
        save_json(self.path, {"version": 1, "games": self.games,
                              "current": self.current.to_dict() if self.current else None,
                              "diff": self.difficulty})
        if notify and self.on_change:
            self.on_change(notify)

    def record(self, game, solved):
        rec = game.summary(solved, self.now_ms())
        self.games = sorted([g for g in self.games if g.get("id") != rec["id"]] + [rec], key=lambda g: g.get("t", 0))
        return rec

    def start(self, difficulty, from_urge=False, rng=None):
        """A fresh puzzle. The game in progress, if any moves were made on it, is kept as unfinished."""
        if difficulty not in DIFFICULTIES:
            difficulty = self.difficulty
        g = self.current
        if g and not g.done and g.moves > 0:
            self.record(g, solved=False)
        self.current = Game.new(difficulty, self.now_ms(), rng, from_urge)
        self.difficulty = difficulty
        self.save("now")
        return self.current

    def changed(self):
        """After a move: stamp the game, finish it if it's solved, save."""
        g = self.current
        g.u = self.now_ms()
        if not g.done and g.solved():
            g.done = True
            g.undo = []
            self.record(g, solved=True)
            self.save("now")
        else:
            self.save("soon")

    def tick_saved(self):
        """The clock moved on: keep the file current without waking the sync."""
        if self.current:
            self.current.u = self.now_ms()
            self.save()

    def playable(self):
        """The game to continue, or None when a new one is needed."""
        return self.current if self.current and not self.current.done else None

    # -- sync

    def shared(self):
        return {"version": 1, "games": list(self.games), "current": self.current.to_dict() if self.current else None}

    def apply_shared(self, merged):
        """Take in the merged sudoku.json. Returns True when anything here changed."""
        games = [g for g in merged.get("games") or [] if isinstance(g, dict) and g.get("id")]
        changed = games != self.games
        self.games = games
        cur = merged.get("current")
        notify = None
        if isinstance(cur, dict) and (self.current is None or cur.get("u", 0) > self.current.u):
            incoming = Game.from_dict(cur)
            if incoming:
                mine = self.current
                if mine and mine.id != incoming.id and not mine.done and mine.moves > 0:
                    self.record(mine, solved=False)  # the other device moved on; this one's progress still counts
                    notify = "now"
                self.current = incoming
                if incoming.diff in DIFFICULTIES:
                    self.difficulty = incoming.diff
                changed = True
        if changed:
            self.save(notify)
        return changed
