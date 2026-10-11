"""The Sudoku board and its controls, drawn with Tk: inside the lock screen and in its own window.

The rules live in sudoku.py; this file only draws the game in app.sudoku (a SudokuLog) and saves
after every move, so a puzzle survives unlocking, closing the window and restarting the app.
"""

import time
import tkinter as tk
from datetime import datetime, timedelta

from sudoku import DIFFICULTIES, best_time, format_clock, label, stats
from theme import (
    ACCENT, ACCENT_BRIGHT, ACCENT_SOFT, BAD, BG, BOX_LINE, FONT, GOOD, GRID, MUTED, PANEL, PANEL_HI, PEER, SAME,
    SEL, TEXT, button, mix, px,
)

FLASH_MS = 500
SAVE_EVERY = 10  # seconds of clock between quiet saves of the elapsed time


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def restyle(b, base, fg=TEXT):
    """Recolour one of theme.button's labels, hover included."""
    b.config(bg=base, fg=fg)
    b.bind("<Enter>", lambda e: b.config(bg=mix(base, "#FFFFFF", 0.08)))
    b.bind("<Leave>", lambda e: b.config(bg=base))


class SudokuView(tk.Frame):
    """Board on the left, controls on the right. `from_urge` marks the game as played during a lock."""

    def __init__(self, master, app, cell=None, from_urge=False, on_stats_change=None):
        super().__init__(master, bg=BG)
        self.app = app
        self.log = app.sudoku
        self.cell = cell or px(52)
        self.from_urge = from_urge
        self.on_stats_change = on_stats_change
        self.sel = None
        self.notes_on = False
        self.paused = False
        self.choosing = False
        self.flash = set()
        self.last_tick = time.monotonic()
        self.since_save = 0.0
        self.side_mode = None
        self.seen_id = None

        if from_urge:
            if self.log.playable() is None:
                self.log.start(self.log.difficulty, from_urge=True)
            elif not self.game.from_urge:
                self.game.from_urge = True
                self.log.save()
        elif self.log.playable() is None:
            self.choosing = True

        size = self.cell * 9 + px(8)
        self.board = tk.Canvas(self, width=size, height=size, bg=GRID, highlightthickness=0, cursor="hand2")
        self.board.pack(side="left", anchor="n")
        self.board.bind("<Button-1>", self._click)
        self.side = tk.Frame(self, bg=BG, width=px(200))
        self.side.pack(side="left", anchor="n", fill="y", padx=(px(18), 0))
        self.side.pack_propagate(False)

        top = self.winfo_toplevel()
        self.key_bind = (top, top.bind("<Key>", self._key, add="+"))
        self.bind("<Destroy>", self._destroyed)
        app.sudoku_views.append(self)

        self.draw()
        self.after(1000, self._tick)

    @property
    def game(self):
        return self.log.current

    def mode(self):
        if self.game is None or self.choosing:
            return "choose"
        return "done" if self.game.done else "play"

    # -- drawing

    def draw(self):
        g = self.game
        if g and g.id != self.seen_id:  # a different puzzle arrived (new game here, or synced in)
            self.seen_id = g.id
            self.sel = None
            self.paused = False
        self.draw_board()
        self.draw_side()

    def refresh(self):
        """After a sync brought in changes."""
        if self.winfo_exists():
            self.draw()

    def cell_box(self, p):
        r, c = divmod(p, 9)
        x = px(2) + c * self.cell + (c // 3) * px(2)
        y = px(2) + r * self.cell + (r // 3) * px(2)
        return x, y, x + self.cell - 1, y + self.cell - 1

    def draw_board(self):
        c = self.board
        c.delete("all")
        g = self.game
        covered = g is not None and (g.done or self.paused) and not self.choosing
        sel_v = g.vals[self.sel] if g and self.sel is not None else 0
        peers = set()
        if g and self.sel is not None and not covered:
            from sudoku import PEERS
            peers = set(PEERS[self.sel])
        for p in range(81):
            x0, y0, x1, y1 = self.cell_box(p)
            fill, colour = PANEL, TEXT
            v = g.vals[p] if g else 0
            if g and not covered:
                if p in self.flash:
                    fill = ACCENT_SOFT
                elif p == self.sel:
                    fill = SEL
                elif sel_v and v == sel_v:
                    fill = SAME
                elif p in peers:
                    fill = PEER
                if not g.puz[p]:
                    colour = BAD if v and v != g.sol[p] else ACCENT_BRIGHT
            elif covered:
                colour = MUTED
            c.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
            if v:
                c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=str(v),
                              font=(FONT, int(self.cell * 0.42), "bold" if g.puz[p] else "normal"), fill=colour)
            elif g and g.notes[p] and not covered:
                third = self.cell / 3
                for n in range(1, 10):
                    if g.notes[p] & (1 << n):
                        nx = x0 + third * ((n - 1) % 3) + third / 2
                        ny = y0 + third * ((n - 1) // 3) + third / 2
                        c.create_text(nx, ny, text=str(n), font=(FONT, max(7, int(self.cell * 0.19))),
                                      fill=ACCENT_BRIGHT if n == sel_v else MUTED)
        # the thick lines between boxes
        size = self.cell * 9 + px(8)
        for i in (1, 2):
            at = px(2) + i * 3 * self.cell + (i - 1) * px(2)
            c.create_rectangle(at - 1, 0, at + px(2), size, fill=BOX_LINE, outline="")
            c.create_rectangle(0, at - 1, size, at + px(2), fill=BOX_LINE, outline="")
        if covered:
            self.draw_cover(g)

    def draw_cover(self, g):
        """A card over the board: the result of a finished game, or the pause note."""
        size = self.cell * 9 + px(8)
        w, h = size * 0.72, px(150)
        x0, y0 = (size - w) / 2, (size - h) / 2
        c = self.board
        c.create_rectangle(x0, y0, x0 + w, y0 + h, fill=PANEL_HI, outline=BOX_LINE)
        if g.done:
            best = best_time(self.log.games, g.diff, except_id=g.id)
            record = best is not None and round(g.elapsed) < best
            c.create_text(size / 2, y0 + px(38), text="Solved", font=(FONT, 24, "bold"), fill=GOOD)
            line = f"{label(g.diff)} in {format_clock(g.elapsed)}" + (", your best yet." if record else ".")
            c.create_text(size / 2, y0 + px(82), text=line, font=(FONT, 12), fill=TEXT)
            c.create_text(size / 2, y0 + px(108), text=f"{plural(g.mistakes, 'mistake')}, {plural(g.hints, 'hint')}.",
                          font=(FONT, 11), fill=MUTED)
        else:
            c.create_text(size / 2, y0 + px(50), text="Paused", font=(FONT, 24, "bold"), fill=TEXT)
            c.create_text(size / 2, y0 + px(96), text="The clock stops while you're away.", font=(FONT, 11), fill=MUTED)

    def draw_side(self):
        mode = self.mode()
        if mode != self.side_mode:
            for w in self.side.winfo_children():
                w.destroy()
            getattr(self, f"build_{mode}")()
            self.side_mode = mode
        if mode == "play":
            self.update_play()

    def build_play(self):
        s = self.side
        head = tk.Frame(s, bg=BG)
        head.pack(fill="x")
        self.diff_label = tk.Label(head, text="", font=(FONT, 14, "bold"), fg=TEXT, bg=BG)
        self.diff_label.pack(side="left")
        self.pause_btn = tk.Label(head, text="⏸", font=("Segoe UI Symbol", 12), fg=TEXT, bg=PANEL_HI,
                                  padx=px(8), pady=px(2), cursor="hand2")
        self.pause_btn.pack(side="right")
        self.pause_btn.bind("<Button-1>", lambda e: self.toggle_pause())
        self.clock_label = tk.Label(head, text="0:00", font=(FONT, 14), fg=TEXT, bg=BG)
        self.clock_label.pack(side="right", padx=(0, px(8)))
        self.mistakes_label = tk.Label(s, text="", font=(FONT, 10), fg=MUTED, bg=BG, anchor="w")
        self.mistakes_label.pack(fill="x", pady=(px(2), 0))

        tools = tk.Frame(s, bg=BG)
        tools.pack(fill="x", pady=(px(12), 0))
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        self.tools = {}
        for i, (key, text) in enumerate((("undo", "Undo"), ("erase", "Erase"), ("notes", "Notes"), ("hint", "Hint"))):
            b = button(tools, text, lambda k=key: self.tool(k), size=10)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, px(6)) if i % 2 == 0 else 0, pady=(0, px(6)))
            self.tools[key] = b

        pad = tk.Frame(s, bg=BG)
        pad.pack(pady=(px(6), 0))
        self.pad = {}
        for n in range(1, 10):
            f = tk.Frame(pad, bg=PANEL_HI, width=px(58), height=px(54), cursor="hand2")
            f.grid(row=(n - 1) // 3, column=(n - 1) % 3, padx=px(3), pady=px(3))
            f.pack_propagate(False)
            big = tk.Label(f, text=str(n), font=(FONT, 17, "bold"), fg=ACCENT_BRIGHT, bg=PANEL_HI)
            small = tk.Label(f, text="", font=(FONT, 8), fg=MUTED, bg=PANEL_HI)
            big.pack(pady=(px(3), 0))
            small.pack()
            for w in (f, big, small):
                w.bind("<Button-1>", lambda e, n=n: self.enter(n))
            self.pad[n] = (f, big, small)
        button(s, "New game", self.choose, size=10).pack(fill="x", pady=(px(12), 0))
        tk.Label(s, text="Keys: 1-9 place, 0 erases, N notes, Ctrl+Z undo, arrows move.", font=(FONT, 8), fg=MUTED,
                 bg=BG, wraplength=px(196), justify="left", anchor="w").pack(fill="x", pady=(px(10), 0))

    def update_play(self):
        g = self.game
        self.diff_label.config(text=label(g.diff))
        self.clock_label.config(text=format_clock(g.elapsed))
        self.pause_btn.config(text="▶" if self.paused else "⏸")
        self.mistakes_label.config(text=f"Mistakes: {g.mistakes}" + (f"  ·  Hints: {g.hints}" if g.hints else ""))
        restyle(self.tools["undo"], PANEL_HI, TEXT if g.undo else MUTED)
        restyle(self.tools["notes"], ACCENT if self.notes_on else PANEL_HI)
        self.tools["notes"].config(text="Notes on" if self.notes_on else "Notes")
        remaining = g.remaining()
        for n, (f, big, small) in self.pad.items():
            if remaining[n] <= 0:
                f.grid_remove()
            else:
                f.grid()
                small.config(text=f"{remaining[n]} left")
                big.config(fg=MUTED if self.notes_on else ACCENT_BRIGHT)

    def build_done(self):
        s = self.side
        g = self.game
        tk.Label(s, text="Nice one.", font=(FONT, 14, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        tk.Label(s, text=f"{label(g.diff)} solved in {format_clock(g.elapsed)}. Want another?", font=(FONT, 10),
                 fg=MUTED, bg=BG, anchor="w", wraplength=px(196), justify="left").pack(fill="x", pady=(px(2), px(10)))
        self.difficulty_buttons(s, g.diff)

    def build_choose(self):
        s = self.side
        g = self.game
        tk.Label(s, text="New puzzle", font=(FONT, 14, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        note = "Pick a difficulty. Every puzzle has exactly one answer."
        if g and not g.done and g.moves:
            note = "Starting over keeps this puzzle on your record as unfinished."
        tk.Label(s, text=note, font=(FONT, 10), fg=MUTED, bg=BG, anchor="w", wraplength=px(196),
                 justify="left").pack(fill="x", pady=(px(2), px(10)))
        self.difficulty_buttons(s, self.log.difficulty)
        if g and not g.done:
            button(s, "Keep playing", self.cancel_choose, size=10).pack(fill="x", pady=(px(14), 0))

    def difficulty_buttons(self, parent, current):
        for key, (name, clues) in DIFFICULTIES.items():
            b = button(parent, f"{name}  ·  {clues} clues", lambda k=key: self.new_game(k), primary=key == current, size=10)
            b.pack(fill="x", pady=(0, px(6)))

    # -- actions

    def new_game(self, difficulty):
        self.log.start(difficulty, from_urge=self.from_urge)
        self.choosing = False
        self.notes_on = False
        self.flash = set()
        self.draw()
        if self.on_stats_change:
            self.on_stats_change()

    def choose(self):
        self.choosing = True
        self.draw()

    def cancel_choose(self):
        self.choosing = False
        self.draw()

    def toggle_pause(self):
        self.paused = not self.paused
        self.draw()

    def toggle_notes(self):
        self.notes_on = not self.notes_on
        self.draw_side()

    def playing(self):
        g = self.game
        return g is not None and not g.done and not self.paused and not self.choosing

    def tool(self, key):
        if key == "notes":
            self.toggle_notes()
        elif key == "undo":
            self.undo()
        elif key == "erase":
            self.erase()
        elif key == "hint":
            self.hint()

    def after_move(self, flash=()):
        self.flash = set(flash)
        self.log.changed()
        if self.game.done:
            self.sel = None
            if self.on_stats_change:
                self.on_stats_change()
        self.draw()
        if self.flash:
            self.after(FLASH_MS, self._unflash)

    def _unflash(self):
        self.flash = set()
        if self.winfo_exists():
            self.draw_board()

    def enter(self, n):
        g = self.game
        if not self.playing() or self.sel is None:
            return
        p = self.sel
        if g.place(p, n, notes=self.notes_on):
            flash = g.completed_units(p) if not self.notes_on and g.vals[p] == g.sol[p] else set()
            self.after_move(flash)

    def erase(self):
        if self.playing() and self.sel is not None and self.game.erase(self.sel):
            self.after_move()

    def undo(self):
        if self.playing() and self.game.undo_move():
            self.after_move()

    def hint(self):
        if not self.playing():
            return
        p = self.game.hint(self.sel)
        if p is not None:
            self.sel = p
            self.after_move(self.game.completed_units(p) | {p})

    # -- input

    def _click(self, e):
        if self.game is None or self.choosing or self.paused or self.game.done:
            return
        for p in range(81):
            x0, y0, x1, y1 = self.cell_box(p)
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                self.sel = p
                self.draw_board()
                return

    def _key(self, e):
        if not self.winfo_exists() or not self.winfo_viewable() or self.game is None or self.choosing:
            return None
        k = e.keysym.removeprefix("KP_")
        if len(k) == 1 and k in "123456789":
            self.enter(int(k))
        elif k in ("BackSpace", "Delete", "0"):
            self.erase()
        elif k in ("n", "N") and self.playing():
            self.toggle_notes()
        elif k in ("z", "Z") and e.state & 0x4:  # Ctrl
            self.undo()
        elif k in ("Up", "Down", "Left", "Right") and self.playing():
            p = 40 if self.sel is None else self.sel
            r, c = divmod(p, 9)
            r = (r + {"Up": 8, "Down": 1}.get(k, 0)) % 9
            c = (c + {"Left": 8, "Right": 1}.get(k, 0)) % 9
            self.sel = r * 9 + c
            self.draw_board()
        else:
            return None
        return "break"

    # -- the clock: runs only while the board is actually on screen

    def _tick(self):
        if not self.winfo_exists():
            return
        now = time.monotonic()
        dt, self.last_tick = now - self.last_tick, now
        if self.playing() and dt <= 5 and self.winfo_viewable():
            self.game.elapsed += dt
            self.since_save += dt
            if self.side_mode == "play":
                self.clock_label.config(text=format_clock(self.game.elapsed))
            if self.since_save >= SAVE_EVERY:
                self.since_save = 0.0
                self.log.tick_saved()
        self.after(1000, self._tick)

    def _destroyed(self, e):
        if e.widget is not self:
            return
        top, bind_id = self.key_bind
        try:
            top.unbind("<Key>", bind_id)
        except tk.TclError:
            pass
        if self in self.app.sudoku_views:
            self.app.sudoku_views.remove(self)
        if self.log.playable() is not None:
            self.log.current.u = self.log.now_ms()
            self.log.save("soon")  # the time spent so far reaches the phone


# --------------------------------------------------------------------------- the window


def stat_tile(parent, name, value, sub, sub_color=MUTED, width=150):
    f = tk.Frame(parent, bg=PANEL, padx=px(12), pady=px(8), width=px(width), height=px(94))
    f.pack(side="left", padx=(0, px(8)))
    f.pack_propagate(False)
    tk.Label(f, text=name, font=(FONT, 9), fg=MUTED, bg=PANEL, anchor="w").pack(fill="x")
    tk.Label(f, text=value, font=(FONT, 20, "bold"), fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
    tk.Label(f, text=sub, font=(FONT, 9), fg=sub_color, bg=PANEL, anchor="w").pack(fill="x")


def when(ms, now):
    t = datetime.fromtimestamp(ms / 1000)
    day = "Today" if t.date() == now.date() else "Yesterday" if t.date() == now.date() - timedelta(days=1) else f"{t:%a %d %b}"
    return f"{day}, {t:%I:%M %p}".replace(" 0", " ")


class SudokuWindow:
    """Play outside a lock, with your record beside the board."""

    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root, bg=BG, padx=px(20), pady=px(16))
        w.title("Urge Button - Sudoku")
        w.resizable(False, False)
        head = tk.Frame(w, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Sudoku", font=(FONT, 20, "bold"), fg=TEXT, bg=BG).pack(side="left")
        button(head, "Close", w.destroy).pack(side="right")
        tk.Label(w, text="Your puzzle is saved as you go, so you can close this and pick it up later, on your phone too. "
                         "Every finished or abandoned game goes on your record.",
                 font=(FONT, 10), fg=MUTED, bg=BG, anchor="w", wraplength=px(1040), justify="left").pack(fill="x", pady=(px(2), px(12)))
        cols = tk.Frame(w, bg=BG)
        cols.pack(fill="x")
        self.view = SudokuView(cols, app, cell=px(54), on_stats_change=self.render_stats)
        self.view.pack(side="left", anchor="n")
        self.stats = tk.Frame(cols, bg=BG)
        self.stats.pack(side="left", anchor="n", padx=(px(28), 0))
        self.render_stats()

    def render_stats(self):
        if not self.win.winfo_exists():
            return
        for child in self.stats.winfo_children():
            child.destroy()
        s = stats(self.app.sudoku.games, self.app.log.now())
        now = self.app.log.now()
        parent = self.stats

        tiles = tk.Frame(parent, bg=BG)
        tiles.pack(fill="x")
        stat_tile(tiles, "Solved", str(s["solved"]), f"of {s['started']} started", width=118)
        stat_tile(tiles, "This week", str(s["week"]), "since Monday", width=118)
        stat_tile(tiles, "Streak", str(s["streak"]), plural(s["streak"], "day") + " in a row" if s["streak"] else "solve one today",
                  GOOD if s["streak"] else MUTED, width=118)

        tk.Label(parent, text="By difficulty", font=(FONT, 12, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x", pady=(px(14), 0))
        tk.Label(parent, text="Solved games only. Perfect means no mistakes and no hints.", font=(FONT, 9), fg=MUTED,
                 bg=BG, anchor="w").pack(fill="x", pady=(0, px(4)))
        table = tk.Frame(parent, bg=PANEL, padx=px(12), pady=px(6))
        table.pack(fill="x")
        heads = ("Level", "Solved", "Best", "Average", "Perfect")
        for j, h in enumerate(heads):
            tk.Label(table, text=h, font=(FONT, 9), fg=MUTED, bg=PANEL, anchor="w" if j == 0 else "e").grid(
                row=0, column=j, sticky="ew", padx=(0, px(10)) if j < 4 else 0, pady=(0, px(2)))
        for i, (key, row) in enumerate(s["by_difficulty"].items(), start=1):
            cells = (label(key),
                     f"{row['solved']} / {row['started']}" if row["started"] else "0",
                     format_clock(row["best"]) if row["best"] is not None else "-",
                     format_clock(row["average"]) if row["average"] is not None else "-",
                     str(row["perfect"]))
            for j, text in enumerate(cells):
                tk.Label(table, text=text, font=(FONT, 10), fg=TEXT if row["solved"] else MUTED, bg=PANEL,
                         anchor="w" if j == 0 else "e").grid(row=i, column=j, sticky="ew", padx=(0, px(10)) if j < 4 else 0, pady=px(2))
        table.columnconfigure(0, weight=1)

        tk.Label(parent, text="Recent games", font=(FONT, 12, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x", pady=(px(14), px(4)))
        recent = s["recent"]
        if not recent:
            tk.Label(parent, text="Finish a puzzle and it shows up here with its time.", font=(FONT, 10), fg=MUTED,
                     bg=BG, anchor="w").pack(fill="x")
        for g in recent:
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", pady=(0, px(3)))
            tk.Label(row, text=label(g.get("diff")), font=(FONT, 10), fg=TEXT, bg=BG, width=7, anchor="w").pack(side="left")
            tk.Label(row, text="solved" if g.get("solved") else "unfinished", font=(FONT, 9), width=9, anchor="w",
                     fg=GOOD if g.get("solved") else MUTED, bg=BG).pack(side="left")
            tk.Label(row, text=when(g["t"], now) + ("  ·  during an urge" if g.get("from_urge") else ""), font=(FONT, 9),
                     fg=MUTED, bg=BG, anchor="w").pack(side="left")
            extras = plural(g.get("mistakes", 0), "mistake") + (f", {plural(g['hints'], 'hint')}" if g.get("hints") else "")
            tk.Label(row, text=extras, font=(FONT, 9), fg=MUTED, bg=BG, anchor="e").pack(side="right")
            tk.Label(row, text=format_clock(g.get("seconds", 0)), font=(FONT, 10), fg=TEXT, bg=BG, anchor="e",
                     width=7).pack(side="right", padx=(px(10), px(8)))


# --------------------------------------------------------------------------- previews


def fake_sudoku_log(path, days=30, seed=7):
    """A made-up record plus a half-played puzzle, for screenshots."""
    import random

    from sudoku import SudokuLog

    rng = random.Random(seed)
    log = SudokuLog(path, now_ms=lambda: int(time.time() * 1000))
    log.games = []
    log.current = None
    now = datetime.now()
    for back in range(days, -1, -1):
        for _ in range(rng.choice([0, 0, 1, 1, 2])):
            diff = rng.choice(["easy", "easy", "medium", "medium", "hard", "expert"])
            base = {"easy": 300, "medium": 520, "hard": 900, "expert": 1400}[diff]
            end = now - timedelta(days=back, hours=rng.randrange(1, 12))
            seconds = max(90, int(rng.gauss(base, base / 4)))
            solved = rng.random() < 0.82
            log.games.append({"id": f"fake{back}{_}", "diff": diff, "started": int(end.timestamp() * 1000) - seconds * 1000,
                              "t": int(end.timestamp() * 1000), "seconds": seconds, "mistakes": rng.choice([0, 0, 1, 2, 3]),
                              "hints": rng.choice([0, 0, 0, 1]), "solved": solved, "from_urge": rng.random() < 0.4,
                              "u": int(end.timestamp() * 1000)})
    log.games.sort(key=lambda g: g["t"])
    g = log.start("medium", rng=random.Random(seed))
    log.on_change = None
    open_cells = [p for p in range(81) if not g.puz[p]]
    for p in open_cells[:14]:
        g.place(p, g.sol[p])
    wrong = open_cells[15]
    g.place(wrong, next(n for n in range(1, 10) if n != g.sol[wrong]))
    for p in open_cells[16:24]:
        for n in rng.sample(range(1, 10), 2):
            g.place(p, n, notes=True)
    g.elapsed = 272
    log.changed()
    return log
