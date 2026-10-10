"""Urge Button - press it when an urge hits; the computer locks for a few minutes.

A small floating button sits on the desktop (or press Ctrl+Alt+U from anywhere).
Pressing it covers every monitor with a lock screen for the configured number of
minutes (default 3), blocks the Windows key / Alt+Tab / Alt+F4 while it is up,
logs the urge, shows your own reasons, and offers five things to do instead:
breathe, go for a walk, put on Spotify, play Sudoku, or reach out to a friend.
You rate the urge when it hits and again when the timer ends, and note what set
it off. Just before an hour that's usually hard, a heads-up appears by the button.

Right-click the button for Progress, logging an urge you handled without the
lock, Settings and Quit. Data lives in %APPDATA%\\UrgeButton.

Ctrl+Alt+Del is handled by Windows itself and cannot be blocked - that is the
deliberate hard exit. The lock always ends on its own when the timer runs out.

    pythonw urge_button.py                       run it
    python urge_button.py --install              desktop shortcut + start with Windows
    python urge_button.py --preview DIR STAGE    screenshot a screen without locking
"""

import math
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import placement
import sync
from blocker import AppBlocker, running_apps
import theme
import winapi
from progress import ProgressWindow, fake_log
from sudoku import check as check_sudoku
from sudoku import make_puzzle
from theme import ACCENT, BAD, BG, FONT, GOOD, MUTED, PANEL, PANEL_HI, TEXT, button, px
from urge_log import (
    CONFIG_PATH, MAX_LOCK_MINUTES, OPTIONS, TRIGGERS, EventLog, clamp_minutes, format_gap, heads_up_due,
    hour_name, load_config, save_json, to_spotify_uri,
)

FRIEND_PROMPTS = [
    "hey, been thinking about you - how's your week going?",
    "random q: what's the best thing that happened to you this week?",
    "want to get food / go for a walk sometime this week?",
    "saw something that reminded me of you. how are you doing?",
    "what are you up to this weekend?",
    "ok I need a recommendation - show, album, anything. go.",
]

FIELD = dict(bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat", highlightthickness=1,
             highlightbackground=PANEL_HI, highlightcolor=ACCENT)

INTENSITY_LABELS = {1: "mild", 2: "", 3: "medium", 4: "", 5: "intense"}


def intensity_picker(master, on_pick, selected=None):
    """Five buttons 1-5; the picked one lights up."""
    row = tk.Frame(master, bg=BG)
    cells = {}

    def pick(n):
        for k, (box, num, cap) in cells.items():
            colour = ACCENT if k == n else PANEL_HI
            for w in (box, num, cap):
                w.config(bg=colour)
        on_pick(n)

    for n in range(1, 6):
        box = tk.Frame(row, bg=PANEL_HI, width=px(72), height=px(64), cursor="hand2")
        box.pack(side="left", padx=px(4))
        box.pack_propagate(False)
        num = tk.Label(box, text=str(n), font=(FONT, 18, "bold"), fg=TEXT, bg=PANEL_HI)
        cap = tk.Label(box, text=INTENSITY_LABELS[n], font=(FONT, 8), fg=TEXT, bg=PANEL_HI)
        num.pack(pady=(px(6), 0))
        cap.pack()
        cells[n] = (box, num, cap)
        for w in (box, num, cap):
            w.bind("<Button-1>", lambda e, n=n: pick(n))
    if selected:
        pick(selected)
    return row


def trigger_chips(master, selected, on_change, per_row=5):
    """Tap-to-toggle chips for what set the urge off. `selected` is a set that gets updated in place."""
    box = tk.Frame(master, bg=BG)
    for i, name in enumerate(TRIGGERS):
        chip = tk.Label(box, text=name, font=(FONT, 11), fg=TEXT, padx=14, pady=7, cursor="hand2",
                        bg=ACCENT if name in selected else PANEL_HI)
        chip.grid(row=i // per_row, column=i % per_row, padx=3, pady=3, sticky="ew")

        def toggle(e, name=name, chip=chip):
            selected.symmetric_difference_update({name})
            chip.config(bg=ACCENT if name in selected else PANEL_HI)
            on_change(selected)

        chip.bind("<Button-1>", toggle)
    return box


def load_photo(path, max_h):
    """A PNG/GIF scaled down to at most max_h pixels tall, or None. Tk reads both without extra libraries."""
    if not path or not Path(path).is_file():
        return None
    try:
        img = tk.PhotoImage(file=path)
    except tk.TclError:
        return None
    factor = max(1, -(-img.height() // max_h))
    return img.subsample(factor, factor) if factor > 1 else img


# --------------------------------------------------------------------------- sudoku board


class SudokuBoard(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.cells = {}
        self.grid_frame = tk.Frame(self, bg=MUTED)
        self.grid_frame.pack()
        self.status = tk.Label(self, text="", font=(FONT, 12), fg=MUTED, bg=BG)
        self.status.pack(pady=(10, 4))
        bar = tk.Frame(self, bg=BG)
        bar.pack()
        button(bar, "Check", self.check).pack(side="left", padx=4)
        button(bar, "New puzzle", self.new).pack(side="left", padx=4)
        self.new()

    def new(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.cells.clear()
        self.puzzle, _ = make_puzzle(random.Random())
        vcmd = (self.register(lambda s: s == "" or (len(s) == 1 and s in "123456789")), "%P")
        size = px(44)
        for br in range(3):
            for bc in range(3):
                box = tk.Frame(self.grid_frame, bg=MUTED)
                box.grid(row=br, column=bc, padx=1, pady=1)
                for i in range(3):
                    for j in range(3):
                        r, c = br * 3 + i, bc * 3 + j
                        slot = tk.Frame(box, width=size, height=size, bg=PANEL)
                        slot.grid(row=i, column=j, padx=1, pady=1)
                        slot.pack_propagate(False)
                        given = self.puzzle[r][c]
                        if given:
                            w = tk.Label(slot, text=str(given), font=(FONT, 18, "bold"), fg=TEXT, bg=PANEL_HI)
                        else:
                            w = tk.Entry(slot, justify="center", font=(FONT, 18), fg=ACCENT, bg=PANEL,
                                         insertbackground=TEXT, relief="flat", validate="key", validatecommand=vcmd)
                            w.bind("<KeyRelease>", self._on_key)
                            self.cells[(r, c)] = w
                        w.pack(fill="both", expand=True)
        self.status.config(text="Fill every row, column and box with 1-9.", fg=MUTED)

    def _on_key(self, e):
        for w in self.cells.values():
            w.config(fg=ACCENT)
        if all(w.get() for w in self.cells.values()):
            self.check()

    def check(self):
        entries = {rc: int(w.get()) for rc, w in self.cells.items() if w.get()}
        wrong, empty = check_sudoku(entries, self.puzzle)
        for rc in wrong:
            self.cells[rc].config(fg=BAD)
        if wrong:
            self.status.config(text=f"{len(wrong)} cell(s) clash - marked in red.", fg=BAD)
        elif empty:
            self.status.config(text=f"No clashes. {empty} to go.", fg=GOOD)
        else:
            self.status.config(text="Solved. Nice.", fg=GOOD)


# --------------------------------------------------------------------------- lock screen


class LockScreen:
    def __init__(self, app, minutes, event, preview=False):
        self.app = app
        self.event = event
        self.preview = preview
        self.remaining = int(minutes * 60)
        self.done = False
        self.blocker = None

        self.win = tk.Toplevel(app.root, bg=BG)
        if preview:
            self.win.geometry(f"{px(1280)}x{px(860)}+40+40")
            self.win.attributes("-topmost", True)
        else:
            x, y, w, h = winapi.virtual_screen()
            self.win.overrideredirect(True)
            self.win.geometry(f"{w}x{h}{x:+d}{y:+d}")
            self.win.attributes("-topmost", True)
            self.win.protocol("WM_DELETE_WINDOW", lambda: None)
            self.blocker = winapi.KeyBlocker()
            self.blocker.start()

        # The black cover spans every monitor; the message sits in the middle of the chosen one.
        self.body = tk.Frame(self.win, bg=BG)
        if preview:
            self.body.place(relx=0.5, rely=0.5, anchor="center")
        else:
            vx, vy = winapi.virtual_screen()[:2]
            mon = placement.find(winapi.monitors(), app.config.get("lock_monitor"))
            cx, cy = placement.centre_in(mon, vx, vy)
            self.body.place(x=cx, y=cy, anchor="center")

        tk.Label(self.body, text="Breathe. This passes.", font=(FONT, 30, "bold"), fg=TEXT, bg=BG).pack()
        tk.Label(self.body, text=f"Urge #{app.log.today()} today  ·  {app.log.this_week()} this week",
                 font=(FONT, 13), fg=MUTED, bg=BG).pack(pady=(6, 0))
        self.why = self.build_why()
        self.clock = tk.Label(self.body, text="", font=(FONT, 64, "bold"), fg=ACCENT, bg=BG)
        self.clock.pack(pady=(10, 18))
        if self.why:
            self.why.pack(before=self.clock, pady=(16, 0))

        self.stage = tk.Frame(self.body, bg=BG)
        self.stage.pack()
        self.show_start_rating()

        self.tick()
        if not preview:
            self.keep_on_top()
        self.win.lift()
        self.win.focus_force()

    # -- stage content

    def clear_stage(self):
        for w in self.stage.winfo_children():
            w.destroy()

    def heading(self, text):
        tk.Label(self.stage, text=text, font=(FONT, 20, "bold"), fg=TEXT, bg=BG).pack()

    def build_why(self):
        """Your own reasons (and photo) from Settings, in a card above the clock. None when there are none."""
        reasons = [r for r in self.app.config.get("reasons", []) if r.strip()][:5]
        self.photo = load_photo(self.app.config.get("reason_image"), px(200))
        if not reasons and not self.photo:
            return None
        card = tk.Frame(self.body, bg=PANEL, padx=px(24), pady=px(14))
        if self.photo:
            tk.Label(card, image=self.photo, bg=PANEL).pack(pady=(0, px(10) if reasons else 0))
        if reasons:
            tk.Label(card, text="WHY YOU'RE DOING THIS", font=(FONT, 9, "bold"), fg=MUTED, bg=PANEL).pack()
            for r in reasons:
                tk.Label(card, text=r, font=(FONT, 15), fg=TEXT, bg=PANEL, wraplength=px(760)).pack(pady=(px(4), 0))
        return card

    def show_why(self, visible):
        if not self.why:
            return
        if visible and not self.why.winfo_ismapped():
            self.why.pack(before=self.clock, pady=(16, 0))
        elif not visible:
            self.why.pack_forget()

    def show_start_rating(self):
        if self.event.get("intensity_start") is not None:
            return self.show_options()
        self.clear_stage()
        tk.Label(self.stage, text="How strong is it right now?", font=(FONT, 14), fg=MUTED, bg=BG).pack(pady=(0, 10))

        def picked(n):
            self.app.log.record_start_intensity(self.event, n)
            self.win.after(250, self.show_options)

        intensity_picker(self.stage, picked).pack()
        button(self.stage, "Skip", self.show_options).pack(pady=(px(16), 0))

    def show_options(self):
        self.show_why(True)
        self.clear_stage()
        tk.Label(self.stage, text="Pick one:", font=(FONT, 14), fg=MUTED, bg=BG).pack(pady=(0, 10))
        row = tk.Frame(self.stage, bg=BG)
        row.pack()
        for key, title, sub in OPTIONS:
            card = tk.Frame(row, bg=PANEL, width=px(230), height=px(130), cursor="hand2")
            card.pack(side="left", padx=8)
            card.pack_propagate(False)
            t = tk.Label(card, text=title, font=(FONT, 15, "bold"), fg=TEXT, bg=PANEL, wraplength=px(200))
            s = tk.Label(card, text=sub, font=(FONT, 11), fg=MUTED, bg=PANEL, wraplength=px(200))
            t.pack(pady=(px(30), 6))
            s.pack()
            for w in (card, t, s):
                w.bind("<Button-1>", lambda e, k=key: self.choose(k))
                w.bind("<Enter>", lambda e, ws=(card, t, s): [x.config(bg=PANEL_HI) for x in ws])
                w.bind("<Leave>", lambda e, ws=(card, t, s): [x.config(bg=PANEL) for x in ws])

    def back_row(self):
        if not self.done:
            button(self.stage, "Back to the options", self.show_options).pack(pady=(18, 0))

    def choose(self, key):
        self.app.log.record_choice(self.event, key)
        getattr(self, f"show_{key}")()

    def show_breathe(self):
        """A circle that grows as you breathe in (4 s), holds (4 s), and shrinks as you breathe out (6 s)."""
        self.clear_stage()
        self.heading("Breathe with me")
        size = px(320)
        c = tk.Canvas(self.stage, width=size, height=size, bg=BG, highlightthickness=0)
        c.pack(pady=(px(6), 0))
        note = tk.Label(self.stage, text="", font=(FONT, 12), fg=MUTED, bg=BG)
        note.pack()
        mid, rmin, rmax = size / 2, size * 0.2, size * 0.47
        c.create_oval(mid - rmax, mid - rmax, mid + rmax, mid + rmax, outline=PANEL_HI, width=2)
        circle = c.create_oval(0, 0, 0, 0, fill=ACCENT, outline="")
        label = c.create_text(mid, mid, text="", fill=TEXT, font=(FONT, 17, "bold"))
        phases = (("Breathe in", 4.0, 0.0, 1.0), ("Hold", 4.0, 1.0, 1.0), ("Breathe out", 6.0, 1.0, 0.0))
        cycle = sum(p[1] for p in phases)
        start = time.monotonic()

        def frame():
            if not c.winfo_exists():
                return
            n, t = divmod(time.monotonic() - start, cycle)
            for name, dur, a, b in phases:
                if t < dur:
                    ease = (1 - math.cos(math.pi * t / dur)) / 2
                    v = a + (b - a) * ease
                    break
                t -= dur
            r = rmin + (rmax - rmin) * v
            c.coords(circle, mid - r, mid - r, mid + r, mid + r)
            c.itemconfig(label, text=name)
            note.config(text=f"Breath {int(n) + 1}. Keep going until the timer ends, or as long as it helps.")
            c.after(33, frame)

        frame()
        self.back_row()

    def show_walk(self):
        self.clear_stage()
        self.heading("Go for a walk")
        lines = (
            "Stand up. Shoes on. Phone in your pocket, not your hand.\n"
            "Walk to the end of the street and back - or just around the block.\n"
            "Notice five things you can see on the way.\n\n"
            "The screen will still be here when you get back."
        )
        tk.Label(self.stage, text=lines, font=(FONT, 14), fg=MUTED, bg=BG, justify="center").pack(pady=12)
        self.back_row()

    def show_spotify(self):
        self.clear_stage()
        self.heading("Music's on")
        msg = tk.Label(self.stage, text="Opening Spotify...", font=(FONT, 14), fg=MUTED, bg=BG)
        msg.pack(pady=12)
        if not self.preview:
            try:
                os.startfile(self.app.config.get("spotify_uri") or "spotify:")
            except OSError:
                msg.config(text="Couldn't open Spotify - is it installed?", fg=BAD)
            else:
                # Spotify opens paused; give it a moment, then press play.
                self.win.after(4000, winapi.press_media_play)
                self.win.after(4000, lambda: msg.winfo_exists() and msg.config(
                    text="Close your eyes for one song. Just listen."))
        button(self.stage, "Pause / play", winapi.press_media_play).pack()
        self.back_row()

    def show_sudoku(self):
        self.show_why(False)  # the board needs the height
        self.clear_stage()
        SudokuBoard(self.stage).pack()
        self.back_row()

    def show_friend(self):
        self.clear_stage()
        friends = [f for f in self.app.config.get("friends", []) if f.strip()]
        who = random.choice(friends) if friends else "someone you haven't talked to in a while"
        self.heading("Reach out")
        tk.Label(self.stage, text=f"Pick up your phone and text {who}:", font=(FONT, 14), fg=MUTED,
                 bg=BG).pack(pady=(12, 6))
        tk.Label(self.stage, text=f"“{random.choice(FRIEND_PROMPTS)}”", font=(FONT, 16, "italic"),
                 fg=TEXT, bg=PANEL, padx=20, pady=14, wraplength=px(700)).pack()
        row = tk.Frame(self.stage, bg=BG)
        row.pack(pady=(14, 0))
        button(row, "Someone else" if len(friends) > 1 else "Different message", self.show_friend).pack(side="left", padx=4)
        if not friends:
            tk.Label(self.stage, text="Tip: add your people in Settings (right-click the button).",
                     font=(FONT, 11), fg=MUTED, bg=BG).pack(pady=(10, 0))
        self.back_row()

    # -- timing

    def tick(self):
        if not self.win.winfo_exists() or self.done:
            return
        if self.remaining <= 0:
            self.finish()
            return
        m, s = divmod(self.remaining, 60)
        self.clock.config(text=f"{m}:{s:02d}")
        self.remaining -= 1
        self.win.after(1000, self.tick)

    def keep_on_top(self):
        if self.done or not self.win.winfo_exists():
            return
        self.win.attributes("-topmost", True)
        self.win.lift()
        try:
            if self.win.focus_get() is None:
                self.win.focus_force()
        except (KeyError, tk.TclError):
            self.win.focus_force()
        self.win.after(300, self.keep_on_top)

    def finish(self):
        self.done = True
        if self.blocker:
            self.blocker.stop()
        self.clock.config(text="You made it.", fg=GOOD, font=(FONT, 48, "bold"))
        self.show_why(False)
        self.clear_stage()
        tk.Label(self.stage, text="How strong is it now?", font=(FONT, 14), fg=MUTED, bg=BG).pack(pady=(0, 10))
        intensity_picker(self.stage, lambda n: self.app.log.record_intensity(self.event, n),
                         self.event.get("intensity")).pack()
        tk.Label(self.stage, text="What set it off? Tap any that fit.", font=(FONT, 14), fg=MUTED,
                 bg=BG).pack(pady=(px(22), 8))
        self.triggers = set(self.event.get("triggers") or [])
        trigger_chips(self.stage, self.triggers, lambda s: self.app.log.record_triggers(self.event, sorted(s))).pack()
        button(self.stage, "Unlock", self.close, primary=True, size=16).pack(pady=(px(24), 0))

    def close(self):
        if self.blocker:
            self.blocker.stop()
        self.win.destroy()
        self.app.on_unlock()


# --------------------------------------------------------------------------- small windows


def small_window(app, title):
    w = tk.Toplevel(app.root, bg=BG, padx=px(20), pady=px(16))
    w.title(title)
    w.attributes("-topmost", True)
    w.resizable(False, False)
    return w


class HeadsUp:
    """A small note beside the button just before an hour that's usually hard."""

    def __init__(self, app, hour):
        self.app = app
        w = self.win = tk.Toplevel(app.root, bg=ACCENT)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        inner = tk.Frame(w, bg=PANEL, padx=px(16), pady=px(12))
        inner.pack(padx=2, pady=2)
        tk.Label(inner, text="Heads up", font=(FONT, 12, "bold"), fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
        tk.Label(inner, text=f"{hour_name(hour)} is usually one of your harder hours.",
                 font=(FONT, 10), fg=MUTED, bg=PANEL, justify="left", anchor="w").pack(fill="x", pady=(4, 0))
        plan = (app.config.get("plan") or "").strip()
        tk.Label(inner, text=f"Your plan: {plan}" if plan else
                 "Have a plan ready: a walk, some music, or a text to someone.",
                 font=(FONT, 11, "bold") if plan else (FONT, 10), fg=TEXT if plan else MUTED, bg=PANEL,
                 justify="left", anchor="w", wraplength=px(360)).pack(fill="x", pady=(4, 10))
        bar = tk.Frame(inner, bg=PANEL)
        bar.pack(fill="x")
        button(bar, "Got it", self.close, size=10).pack(side="right")
        button(bar, "Lock now", self.lock_now, primary=True, size=10).pack(side="right", padx=6)
        self.place()
        w.after(120_000, self.close)

    def place(self):
        w, root = self.win, self.app.root
        w.update_idletasks()
        ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
        bx, by, bw, bh = root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height()
        mons = winapi.monitors()
        mon = next((m for m in mons if m.contains(bx + bw // 2, by + bh // 2)), placement.find(mons, None))
        x = max(mon.x + px(8), min(bx + bw - ww, mon.x + mon.w - ww - px(8)))
        y = by - wh - px(8)
        if y < mon.y:
            y = by + bh + px(8)  # no room above: show it below
        w.geometry(f"{x:+d}{y:+d}")

    def lock_now(self):
        self.close()
        self.app.trigger()

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()


class LogOwnWindow:
    """Log an urge you rode out without locking the screen."""

    def __init__(self, app):
        self.app = app
        self.intensity = None
        self.triggers = set()
        w = self.win = small_window(app, "Urge Button - Log an urge")
        tk.Label(w, text="Handled one on your own?", font=(FONT, 16, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(w, text="It still counts - logging it keeps the picture honest. How strong was it?",
                 font=(FONT, 10), fg=MUTED, bg=BG).pack(anchor="w", pady=(2, 12))
        intensity_picker(w, self._pick).pack(anchor="w")
        tk.Label(w, text="What set it off?", font=(FONT, 10), fg=MUTED, bg=BG).pack(anchor="w", pady=(14, 6))
        trigger_chips(w, self.triggers, lambda s: None, per_row=3).pack(anchor="w")
        bar = tk.Frame(w, bg=BG)
        bar.pack(fill="x", pady=(16, 0))
        button(bar, "Log it", self.save, primary=True).pack(side="right")
        button(bar, "Cancel", w.destroy).pack(side="right", padx=6)

    def _pick(self, n):
        self.intensity = n

    def save(self):
        self.app.log.record_logged(self.intensity, sorted(self.triggers))
        self.app.refresh_counts()
        self.win.destroy()


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        w = self.win = small_window(app, "Urge Button - Settings")
        cols = tk.Frame(w, bg=BG)
        cols.pack(fill="both")
        left = tk.Frame(cols, bg=BG)
        left.pack(side="left", anchor="n", padx=(0, px(28)))
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", anchor="n", padx=(0, px(28)))
        third = tk.Frame(cols, bg=BG)
        third.pack(side="left", anchor="n")

        def label(parent, text, top=10):
            tk.Label(parent, text=text, font=(FONT, 11), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(top, 2))

        # Left: where things go, startup
        self.build_placement(left)
        tk.Frame(left, bg=PANEL_HI, height=1).pack(fill="x", pady=(16, 4))
        self.startup = tk.BooleanVar(value=winapi.starts_with_windows())
        tk.Checkbutton(left, text="Start with Windows", variable=self.startup, font=(FONT, 11), fg=TEXT, bg=BG,
                       selectcolor=PANEL, activebackground=BG, activeforeground=TEXT).pack(anchor="w", pady=(8, 0))
        self.heads_up = tk.BooleanVar(value=app.config.get("heads_up", True))
        tk.Checkbutton(left, text="Heads-up before my usual hard hours", variable=self.heads_up, font=(FONT, 11),
                       fg=TEXT, bg=BG, selectcolor=PANEL, activebackground=BG,
                       activeforeground=TEXT).pack(anchor="w", pady=(4, 0))
        risky = sorted(app.log.risky_hours())
        tk.Label(left, text=("Your hard hours right now: " + ", ".join(hour_name(h) for h in risky)) if risky
                 else "Shows up once your history has a pattern.", font=(FONT, 10), fg=MUTED, bg=BG,
                 anchor="w").pack(fill="x", padx=(px(22), 0))
        label(left, "Your plan for a hard hour (shown in the heads-up)")
        self.plan = tk.Entry(left, width=44, font=(FONT, 11), **FIELD)
        self.plan.insert(0, app.config.get("plan", ""))
        self.plan.pack(anchor="w", ipady=3)
        tk.Label(left, text="e.g. Phone in the other room, make tea, walk round the block.", font=(FONT, 9),
                 fg=MUTED, bg=BG, anchor="w").pack(fill="x")
        hotkey = "Ctrl+Alt+U also triggers the lock from anywhere." if app.hotkey_ok else \
            "Ctrl+Alt+U is taken by another app, so only the button works."
        tk.Label(left, text=hotkey, font=(FONT, 10), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(6, 0))

        # Right: the lock itself
        tk.Label(right, text="The lock", font=(FONT, 13, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        label(right, f"Lock length (minutes, 1-{MAX_LOCK_MINUTES})", top=6)
        self.minutes = tk.Spinbox(right, from_=1, to=MAX_LOCK_MINUTES, width=6, font=(FONT, 12), **FIELD,
                                  buttonbackground=PANEL_HI)
        self.minutes.delete(0, "end")
        self.minutes.insert(0, str(app.config["lock_minutes"]))
        self.minutes.pack(anchor="w")

        label(right, "Your reasons, one per line. They show on the lock screen.")
        self.reasons = tk.Text(right, width=46, height=4, font=(FONT, 11), padx=6, pady=4, wrap="word", **FIELD)
        self.reasons.insert("1.0", "\n".join(app.config.get("reasons", [])))
        self.reasons.pack(anchor="w")

        label(right, "Photo above your reasons (PNG or GIF, optional)")
        row = tk.Frame(right, bg=BG)
        row.pack(fill="x")
        self.image = tk.Entry(row, width=34, font=(FONT, 10), **FIELD)
        self.image.insert(0, app.config.get("reason_image", ""))
        self.image.pack(side="left", fill="x", expand=True, ipady=4)
        button(row, "Choose...", self.choose_image, size=10).pack(side="left", padx=(6, 0))
        button(row, "Clear", lambda: self.image.delete(0, "end"), size=10).pack(side="left", padx=(4, 0))

        label(right, "Spotify playlist link (blank just opens Spotify)")
        self.spotify = tk.Entry(right, width=46, font=(FONT, 11), **FIELD)
        uri = app.config.get("spotify_uri", "")
        self.spotify.insert(0, "" if uri == "spotify:" else uri)
        self.spotify.pack(anchor="w", ipady=3)

        label(right, "Friends to reach out to (one per line)")
        self.friends = tk.Text(right, width=46, height=4, font=(FONT, 11), padx=6, pady=4, **FIELD)
        self.friends.insert("1.0", "\n".join(app.config.get("friends", [])))
        self.friends.pack(anchor="w")

        # Third: blocking and sync
        tk.Label(third, text="Block apps", font=(FONT, 13, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        label(third, "Close these during a lock and the cooldown (one per line)", top=6)
        self.block = tk.Text(third, width=36, height=5, font=(FONT, 11), padx=6, pady=4, **FIELD)
        self.block.insert("1.0", "\n".join(app.config.get("block_apps", [])))
        self.block.pack(anchor="w")
        pick = tk.Frame(third, bg=BG)
        pick.pack(fill="x", pady=(6, 0))
        self.running = tk.StringVar(value="Add a running app...")
        apps = running_apps() or ["(no apps found)"]
        menu = tk.OptionMenu(pick, self.running, *apps, command=self.add_block_app)
        menu.config(font=(FONT, 10), bg=PANEL, fg=TEXT, activebackground=PANEL_HI, activeforeground=TEXT,
                    highlightthickness=0, relief="flat", anchor="w", width=26)
        menu["menu"].config(font=(FONT, 10), bg=PANEL, fg=TEXT, activebackground=ACCENT)
        menu.pack(side="left")
        row2 = tk.Frame(third, bg=BG)
        row2.pack(fill="x", pady=(8, 0))
        tk.Label(row2, text="Cooldown after the lock (minutes)", font=(FONT, 11), fg=MUTED, bg=BG).pack(side="left")
        self.block_minutes = tk.Spinbox(row2, from_=0, to=240, width=5, font=(FONT, 11), **FIELD,
                                        buttonbackground=PANEL_HI)
        self.block_minutes.delete(0, "end")
        self.block_minutes.insert(0, str(app.config.get("block_minutes", 30)))
        self.block_minutes.pack(side="left", padx=(8, 0))
        tk.Label(third, text="Your work stays open in everything else. Websites need an admin setup; ask for it.",
                 font=(FONT, 9), fg=MUTED, bg=BG, anchor="w", wraplength=px(330), justify="left").pack(fill="x", pady=(4, 0))

        tk.Frame(third, bg=PANEL_HI, height=1).pack(fill="x", pady=(16, 4))
        tk.Label(third, text="Sync with your phone", font=(FONT, 13, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        self.sync_on = tk.BooleanVar(value=app.config.get("sync", True))
        tk.Checkbutton(third, text="Keep one history on PC and phone", variable=self.sync_on, font=(FONT, 11),
                       fg=TEXT, bg=BG, selectcolor=PANEL, activebackground=BG,
                       activeforeground=TEXT).pack(anchor="w", pady=(4, 0))
        label(third, "Private GitHub repo for your history")
        self.sync_repo = tk.Entry(third, width=36, font=(FONT, 11), **FIELD)
        self.sync_repo.insert(0, app.config.get("sync_repo") or sync.DEFAULT_REPO)
        self.sync_repo.pack(anchor="w", ipady=3)
        label(third, "GitHub token (blank uses this PC's GitHub login)")
        self.sync_token = tk.Entry(third, width=36, font=(FONT, 11), show="•", **FIELD)
        self.sync_token.insert(0, app.config.get("sync_token", ""))
        self.sync_token.pack(anchor="w", ipady=3)
        row3 = tk.Frame(third, bg=BG)
        row3.pack(fill="x", pady=(8, 0))
        self.sync_label = tk.Label(row3, text=app.sync_status, font=(FONT, 10), fg=MUTED, bg=BG, anchor="w",
                                   wraplength=px(240), justify="left")
        self.sync_label.pack(side="left", fill="x", expand=True)
        button(row3, "Sync now", lambda: app.sync_now(), size=10).pack(side="right")
        self._watch_sync()

        bar = tk.Frame(w, bg=BG)
        bar.pack(fill="x", pady=(16, 0))
        button(bar, "Save", self.save, primary=True).pack(side="right")
        button(bar, "Cancel", w.destroy).pack(side="right", padx=6)

    def add_block_app(self, name):
        if name.startswith("("):
            return
        have = [x.strip().lower() for x in self.block.get("1.0", "end").splitlines() if x.strip()]
        if name.lower() not in have:
            text = self.block.get("1.0", "end").strip()
            self.block.delete("1.0", "end")
            self.block.insert("1.0", (text + "\n" if text else "") + name)
        self.running.set("Add a running app...")

    def _watch_sync(self):
        if self.win.winfo_exists():
            self.sync_label.config(text=self.app.sync_status,
                                   fg=BAD if self.app.sync_status.startswith("Sync problem") else MUTED)
            self.win.after(1000, self._watch_sync)

    def choose_image(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.win, title="Choose a photo",
                                          filetypes=[("Images", "*.png *.gif"), ("All files", "*.*")])
        if path:
            self.image.delete(0, "end")
            self.image.insert(0, path)

    # -- where the button and the lock message go (these apply straight away)

    def build_placement(self, w):
        app = self.app
        self.mons = winapi.monitors()
        labels = [placement.label(m, i) for i, m in enumerate(self.mons)]
        by_label = dict(zip(labels, self.mons))

        head = tk.Frame(w, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Where things go", font=(FONT, 13, "bold"), fg=TEXT, bg=BG).pack(side="left")
        if len(self.mons) > 1:
            button(head, "Identify monitors", self.identify, size=10).pack(side="right")
        tk.Label(w, text="Changes here move the button right away. You can also drag it anywhere.",
                 font=(FONT, 10), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(2, 0))

        def current_label(name):
            mon = placement.find(self.mons, name)
            return labels[self.mons.index(mon)] if mon else ""

        def dropdown(parent, var, on_pick):
            menu = tk.OptionMenu(parent, var, *labels, command=on_pick)
            menu.config(font=(FONT, 11), bg=PANEL, fg=TEXT, activebackground=PANEL_HI, activeforeground=TEXT,
                        highlightthickness=0, relief="flat", anchor="w", width=30)
            menu["menu"].config(font=(FONT, 11), bg=PANEL, fg=TEXT, activebackground=ACCENT)
            return menu

        tk.Label(w, text="Button on", font=(FONT, 11), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(10, 2))
        self.button_mon = tk.StringVar(value=current_label(app.config.get("button_monitor")))
        dropdown(w, self.button_mon, lambda lab: app.move_button(monitor_name=by_label[lab].name)).pack(anchor="w")

        tk.Label(w, text="Button position", font=(FONT, 11), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(10, 2))
        grid = tk.Frame(w, bg=BG)
        grid.pack(anchor="w")
        self.anchor_cells = {}
        for i, (key, text) in enumerate(placement.ANCHORS):
            cell = tk.Label(grid, text=text, font=(FONT, 10), fg=TEXT, bg=PANEL_HI, width=13, pady=7, cursor="hand2")
            cell.grid(row=i // 3, column=i % 3, padx=(0, 4), pady=(0, 4))
            cell.bind("<Button-1>", lambda e, k=key: self.pick_anchor(k))
            self.anchor_cells[key] = cell
        self.paint_anchor()

        tk.Label(w, text="Lock-screen message on (the whole screen still goes dark)", font=(FONT, 11),
                 fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(10, 2))
        self.lock_mon = tk.StringVar(value=current_label(app.config.get("lock_monitor")))

        def pick_lock(lab):
            app.config["lock_monitor"] = by_label[lab].name
            app.save_config()

        dropdown(w, self.lock_mon, pick_lock).pack(anchor="w")

    def pick_anchor(self, key):
        self.app.move_button(anchor=key)
        self.paint_anchor()

    def paint_anchor(self):
        current = self.app.config.get("button_anchor")
        for key, cell in self.anchor_cells.items():
            cell.config(bg=ACCENT if key == current else PANEL_HI)

    def identify(self):
        """Flash each monitor's number in its middle for a few seconds."""
        for i, m in enumerate(self.mons):
            t = tk.Toplevel(self.win, bg=ACCENT)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            size = px(200)
            t.geometry(f"{size}x{size}{m.x + (m.w - size) // 2:+d}{m.y + (m.h - size) // 2:+d}")
            tk.Label(t, text=str(i + 1), font=(FONT, 96, "bold"), fg=TEXT, bg=ACCENT).pack(expand=True)
            t.after(2500, t.destroy)

    def save(self):
        cfg = self.app.config
        cfg["lock_minutes"] = clamp_minutes(self.minutes.get())
        cfg["spotify_uri"] = to_spotify_uri(self.spotify.get().strip())
        cfg["friends"] = [f.strip() for f in self.friends.get("1.0", "end").splitlines() if f.strip()]
        cfg["reasons"] = [r.strip() for r in self.reasons.get("1.0", "end").splitlines() if r.strip()]
        cfg["reason_image"] = self.image.get().strip()
        cfg["heads_up"] = bool(self.heads_up.get())
        cfg["plan"] = self.plan.get().strip()
        cfg["block_apps"] = [x.strip() for x in self.block.get("1.0", "end").splitlines() if x.strip()]
        try:
            cfg["block_minutes"] = max(0, min(240, int(self.block_minutes.get())))
        except ValueError:
            pass
        sync_changed = (cfg.get("sync_repo"), cfg.get("sync_token"), cfg.get("sync")) != (
            self.sync_repo.get().strip(), self.sync_token.get().strip(), bool(self.sync_on.get()))
        cfg["sync_repo"] = self.sync_repo.get().strip() or sync.DEFAULT_REPO
        cfg["sync_token"] = self.sync_token.get().strip()
        cfg["sync"] = bool(self.sync_on.get())
        if sync_changed:
            self.app.schedule_sync(500)
        self.app.save_config()
        if self.startup.get() != winapi.starts_with_windows():
            winapi.set_start_with_windows(self.startup.get())
        self.win.destroy()


# --------------------------------------------------------------------------- app


class App:
    W, H = 176, 70

    def __init__(self, log=None, hotkey=True):
        self.config = load_config()
        self.log = log or EventLog()
        self.lock = None
        self.settings = None
        self.heads_up_key = None

        root = self.root = tk.Tk()
        theme.init_scale(root)
        root.title("Urge Button")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=ACCENT)

        self.place_button()

        self.face = tk.Frame(root, bg=ACCENT, cursor="hand2")
        self.face.pack(fill="both", expand=True)
        self.title = tk.Label(self.face, text="URGE", font=(FONT, 16, "bold"), fg=TEXT, bg=ACCENT)
        self.sub = tk.Label(self.face, text="", font=(FONT, 9), fg=TEXT, bg=ACCENT)
        self.title.pack(pady=(px(8), 0))
        self.sub.pack()

        # Settings gear in the corner; its clicks never start a lock or a drag.
        gear = tk.Label(self.face, text="⚙", font=("Segoe UI Symbol", 11), fg=TEXT, bg=ACCENT, cursor="hand2")
        gear.place(relx=1.0, x=-px(4), y=px(1), anchor="ne")
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.bind("<Enter>", lambda e: gear.config(fg="#C9CCFF"))
        gear.bind("<Leave>", lambda e: gear.config(fg=TEXT))

        menu = self.menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="Progress", command=self.show_progress)
        menu.add_command(label="Log an urge I handled on my own", command=lambda: LogOwnWindow(self))
        menu.add_separator()
        menu.add_command(label="Settings", command=self.open_settings)
        menu.add_command(label="Quit", command=root.destroy)

        for wdg in (self.face, self.title, self.sub):
            wdg.bind("<ButtonPress-1>", self._press)
            wdg.bind("<B1-Motion>", self._drag)
            wdg.bind("<ButtonRelease-1>", self._release)
            wdg.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        self.hotkey = winapi.Hotkey()
        self.hotkey_ok = self.hotkey.start() if hotkey else False

        # Closing chosen apps during a lock and the cooldown after it
        self.app_blocker = AppBlocker()
        self._block_loop()

        # Sync with the phone through the private data repo
        self.online = hotkey  # previews run offline
        self.sync_status = "Not synced yet"
        self._sync_job = None
        self._syncing = False
        self._sync_again = False
        self._sync_results = queue.Queue()
        self.log.on_change = lambda: self.schedule_sync(3000)
        if self.online:
            self.schedule_sync(1500)
            self._sync_every()

        self._poll_hotkey()
        self._tick_counts()

    # -- blocking

    def _block_loop(self):
        if self.app_blocker.active():
            threading.Thread(target=self.app_blocker.tick, daemon=True).start()
        self.root.after(4000, self._block_loop)

    # -- sync

    def _sync_every(self):
        self.schedule_sync(0)
        self.root.after(5 * 60_000, self._sync_every)

    def schedule_sync(self, delay=3000):
        if not self.online or not self.config.get("sync", True):
            return
        if self._sync_job:
            self.root.after_cancel(self._sync_job)
        self._sync_job = self.root.after(delay, self.sync_now)

    def sync_now(self):
        self._sync_job = None
        if self._syncing:
            self._sync_again = True
            return
        self._syncing = True
        snapshot = self.log.shared()
        repo = self.config.get("sync_repo") or sync.DEFAULT_REPO
        token = self.config.get("sync_token") or None

        def work():
            try:
                tok = token or sync.gh_cli_token()
                if not tok:
                    raise sync.SyncError("no GitHub token yet - add one in Settings")
                self._sync_results.put(("ok", sync.sync(snapshot, sync.GitHubFile(repo, tok))))
            except Exception as e:  # never let a network problem take the app down
                self._sync_results.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _sync_done(self, kind, value):
        self._syncing = False
        if kind == "ok":
            if self.log.apply_shared(value):
                self.refresh_counts()
            self.sync_status = f"Synced at {datetime.now():%I:%M %p}".replace(" 0", " ")
        else:
            self.sync_status = f"Sync problem: {value}"
        if self._sync_again:
            self._sync_again = False
            self.schedule_sync(500)

    def _poll_hotkey(self):
        while not self.hotkey.presses.empty():
            self.hotkey.presses.get_nowait()
            self.trigger()
        while not self._sync_results.empty():
            self._sync_done(*self._sync_results.get_nowait())
        self.root.after(150, self._poll_hotkey)

    def _tick_counts(self):
        self.refresh_counts()
        self.check_heads_up()
        self.root.after(30_000, self._tick_counts)

    def check_heads_up(self):
        if not self.config.get("heads_up", True) or self.lock is not None:
            return
        now = self.log.now()
        key = heads_up_due(now, self.log.risky_hours(), self.log.since_last(), self.heads_up_key)
        if key:
            self.heads_up_key = key
            HeadsUp(self, int(key[-2:]))

    def refresh_counts(self):
        since = self.log.since_last()
        gap = "none yet" if since is None else f"{format_gap(since)} ago" if since >= 60 else "just now"
        left = self.app_blocker.remaining() if hasattr(self, "app_blocker") else 0
        if left and self.lock is None:
            gap = f"apps blocked {max(1, left // 60)}m"
        self.sub.config(text=f"today {self.log.today()}  ·  {gap}")

    def save_config(self):
        save_json(CONFIG_PATH, self.config)

    def open_settings(self):
        if self.settings and self.settings.win.winfo_exists():
            self.settings.win.lift()
            self.settings.win.focus_force()
        else:
            self.settings = SettingsWindow(self)

    def place_button(self):
        """Put the button where the config says, falling back to the main monitor if that spot is gone."""
        w, h = px(self.W), px(self.H)
        mons = winapi.monitors()
        cfg = self.config
        x, y = cfg.get("button_x"), cfg.get("button_y")
        anchor = cfg.get("button_anchor") or "bottom-right"
        if anchor == "custom" and x is not None and y is not None and placement.on_screen(mons, x, y, w, h):
            pass
        else:
            if anchor == "custom":
                anchor = "bottom-right"
            mon = placement.find(mons, cfg.get("button_monitor"))
            x, y = placement.anchor_position(mon, w, h, anchor, margin=px(24))
        self.root.geometry(f"{w}x{h}{x:+d}{y:+d}")

    def move_button(self, monitor_name=None, anchor=None):
        if monitor_name is not None:
            self.config["button_monitor"] = monitor_name
        if anchor is not None:
            self.config["button_anchor"] = anchor
        elif self.config.get("button_anchor") == "custom":
            self.config["button_anchor"] = "bottom-right"  # a new monitor needs a spot on it
        self.place_button()
        self.save_config()

    # click vs drag: a press that moves more than a few pixels is a drag.

    def _press(self, e):
        self._start = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._moved = False

    def _drag(self, e):
        sx, sy, wx, wy = self._start
        dx, dy = e.x_root - sx, e.y_root - sy
        if abs(dx) + abs(dy) > 4:
            self._moved = True
        if self._moved:
            self.root.geometry(f"{wx + dx:+d}{wy + dy:+d}")

    def _release(self, e):
        if self._moved:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            cfg = self.config
            cfg["button_x"], cfg["button_y"], cfg["button_anchor"] = x, y, "custom"
            here = [m for m in winapi.monitors() if m.contains(x + px(self.W) // 2, y + px(self.H) // 2)]
            if here:
                cfg["button_monitor"] = here[0].name
            self.save_config()
        else:
            self.trigger()

    def trigger(self, preview=False):
        if self.lock is not None:
            return
        minutes = self.config["lock_minutes"]
        event = self.log.record_press(minutes)
        if self.config.get("block_apps") and not preview:
            cooldown = max(0, int(self.config.get("block_minutes") or 0))
            self.app_blocker.start(self.config["block_apps"], (minutes + cooldown) * 60)
            threading.Thread(target=self.app_blocker.tick, daemon=True).start()
        self.refresh_counts()
        self.lock = LockScreen(self, minutes, event, preview=preview)

    def on_unlock(self):
        self.lock = None
        self.refresh_counts()

    def show_progress(self):
        ProgressWindow(self.root, self.log)


# --------------------------------------------------------------------------- entry


def run_preview(out_dir, stage):
    """Render a screen in a normal window against a throwaway log (no lock, no hook), screenshot it, exit."""
    from PIL import ImageGrab

    out = Path(out_dir)
    app = App(log=fake_log(out / "preview-events.json"), hotkey=False)
    app.save_config = lambda: None  # previews never touch the real settings
    app.config["reasons"] = ["I want my evenings back.", "Future me is proud of every one of these."]
    target = None
    if stage == "progress":
        target = ProgressWindow(app.root, app.log).win
        target.attributes("-topmost", True)
    elif stage == "logged":
        target = LogOwnWindow(app).win
    elif stage == "settings":
        target = SettingsWindow(app).win
    elif stage == "button":
        target = app.root
    elif stage == "headsup":
        target = HeadsUp(app, 21).win
    else:
        app.trigger(preview=True)
        target = app.lock.win
        if stage == "finish":
            app.lock.finish()
        elif stage == "start":
            pass
        elif stage == "options":
            app.lock.show_options()
        else:
            getattr(app.lock, f"show_{stage}")()

    def shoot():
        target.lift()
        target.update()
        box = (target.winfo_rootx(), target.winfo_rooty(),
               target.winfo_rootx() + target.winfo_width(), target.winfo_rooty() + target.winfo_height())
        ImageGrab.grab(bbox=box, all_screens=True).save(out / f"preview-{stage}.png")
        app.root.destroy()

    app.root.after(1500, shoot)
    app.root.mainloop()


def main():
    winapi.set_dpi_aware()
    if len(sys.argv) >= 2 and sys.argv[1] == "--install":
        desk = winapi.desktop_link()
        print("Desktop shortcut:", "ok" if winapi.make_shortcut(desk) else "FAILED", desk)
        print("Start with Windows:", "ok" if winapi.set_start_with_windows(True) else "FAILED", winapi.STARTUP_LINK)
        import subprocess
        subprocess.Popen([str(winapi.pythonw()), str(winapi.SCRIPT)], cwd=str(winapi.SCRIPT.parent),
                         creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        print("Started. The URGE button is in the bottom-right corner (it was already running if you see only one).")
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--preview":
        run_preview(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "options")
        return
    if not winapi.single_instance():
        return
    App().root.mainloop()


if __name__ == "__main__":
    main()
