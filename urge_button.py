"""Urge Button - press it when an urge hits; the computer locks for a few minutes.

A small floating button sits on the desktop (or press Ctrl+Alt+U from anywhere).
Pressing it covers every monitor with a lock screen for the configured number of
minutes (default 3), blocks the Windows key / Alt+Tab / Alt+F4 while it is up,
logs the urge, shows your own reasons, and offers five things to do instead:
breathe, go for a walk, put on Spotify, play Sudoku, or reach out to a friend.
You rate the urge when it hits and again when the timer ends, and note what set
it off. Just before an hour that's usually hard, a heads-up appears by the button.

Beside it sits a smaller Bored button (or Ctrl+Alt+B): no lock, just three quick
things to do for five minutes, and the press is tracked on its own, apart from urges.

Right-click either button for Progress, Sudoku, logging an urge you handled without
the lock, Settings and Quit. Data lives in %APPDATA%\\UrgeButton.

Ctrl+Alt+Del is handled by Windows itself and cannot be blocked - that is the
deliberate hard exit. The lock always ends on its own when the timer runs out.

    pythonw urge_button.py                       run it
    python urge_button.py --install              desktop shortcut + start with Windows
    python urge_button.py --preview DIR STAGE    screenshot a screen without locking

Sudoku (right-click the button, or pick it during a lock) is saved as you go and tracked, and
shares one record with the phone through sudoku.json in the same private repo as the urges.
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

import food
import placement
import sync
from blocker import AppBlocker, running_apps
from updater import CHECK_SECONDS, RESTART_POLL_SECONDS, Updater, restart_allowed
import theme
import winapi
from progress import ProgressWindow, fake_log
from sudoku import SudokuLog
from sudoku_ui import SudokuView, SudokuWindow, fake_sudoku_log
from theme import ACCENT, ACCENT_BRIGHT, BAD, BG, CALM, FONT, GOOD, MUTED, PANEL, PANEL_HI, TEXT, WARN, button, mix, px
from urge_log import (
    BORED_IDEAS, CONFIG_PATH, MAX_LOCK_MINUTES, OPTIONS, STOP_LINES, STRETCHES, SURFACES, TRIGGERS, Countdown,
    EventLog, activity_seconds, bored_ideas, bored_key, bored_name, clamp_minutes, clock_text, cluster_minutes,
    finish_line, format_gap, heads_up_due, hour_name, load_config, pick_ideas, save_json, stretch_at, to_spotify_uri,
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


def friend_pick(cfg):
    """Who to text and what to say: (name, message, your friends list). Shared by the lock and the Bored panel."""
    friends = [f for f in cfg.get("friends", []) if f.strip()]
    who = random.choice(friends) if friends else "someone you haven't talked to in a while"
    return who, random.choice(FRIEND_PROMPTS), friends


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}{'es' if word.endswith('s') else 's'}"


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


# --------------------------------------------------------------------------- lock screen


class LockScreen:
    def __init__(self, app, minutes, event, preview=False, note=None):
        self.app = app
        self.event = event
        self.preview = preview
        self.remaining = int(minutes * 60)
        self.done = False
        self.playing = False  # the Sudoku board is up (the clock shrinks to make room)
        self.blocker = None

        self.win = tk.Toplevel(app.root, bg=BG)
        if preview:
            self.win.geometry(f"{px(1280)}x{px(860)}+40+40")
            self.win.attributes("-topmost", True)
        else:
            x, y, w, h = winapi.virtual_screen()
            self.win.overrideredirect(True)
            self.win.geometry(placement.geometry(x, y, w, h))
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
        if note:
            tk.Label(self.body, text=note, font=(FONT, 12), fg=WARN, bg=BG, wraplength=px(760)).pack(pady=(6, 0))
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
        self.set_playing(False)
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
        problem = self.app.play_music()
        if problem:
            msg.config(text=problem, fg=BAD)
        elif not self.preview:
            self.win.after(4000, lambda: msg.winfo_exists() and msg.config(
                text="Close your eyes for one song. Just listen."))
        button(self.stage, "Pause / play", winapi.press_media_play).pack()
        self.back_row()

    def set_playing(self, on):
        if on != self.playing and not self.done:
            self.playing = on
            self.clock.config(font=(FONT, 34 if on else 64, "bold"))
            self.clock.pack_configure(pady=(4, 10) if on else (10, 18))

    def show_sudoku(self):
        """Carries on the saved puzzle, or starts one at the last difficulty. Saved as you go."""
        self.show_why(False)  # the board needs the height
        self.set_playing(True)
        self.clear_stage()
        SudokuView(self.stage, self.app, cell=px(46), from_urge=True).pack()
        self.back_row()

    def show_friend(self):
        self.clear_stage()
        who, msg, friends = friend_pick(self.app.config)
        self.heading("Reach out")
        tk.Label(self.stage, text=f"Pick up your phone and text {who}:", font=(FONT, 14), fg=MUTED,
                 bg=BG).pack(pady=(12, 6))
        tk.Label(self.stage, text=f"“{msg}”", font=(FONT, 16, "italic"),
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
        self.clock.pack_configure(pady=(10, 18))
        self.show_why(False)
        keep = self.playing and self.app.sudoku.playable() is not None
        self.clear_stage()
        if keep:
            tk.Label(self.stage, text="Your puzzle is saved. Pick it up any time from Sudoku in the button's menu.",
                     font=(FONT, 11), fg=MUTED, bg=BG).pack(pady=(0, 12))
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


def beside_button(app, w):
    """Put a small window just above the floating button (below it when there's no room), on its monitor."""
    root = app.root
    w.update_idletasks()
    ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
    bx, by, bw, bh = root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height()
    mons = winapi.monitors()
    mon = next((m for m in mons if m.contains(bx + bw // 2, by + bh // 2)), placement.find(mons, None))
    x = max(mon.x + px(8), min(bx + bw - ww, mon.x + mon.w - ww - px(8)))
    y = by - wh - px(8)
    if y < mon.y:
        y = by + bh + px(8)  # no room above: show it below
    w.geometry(placement.geometry(x, y))


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
        beside_button(app, w)
        w.after(120_000, self.close)

    def lock_now(self):
        self.close()
        self.app.trigger()

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()


class FoodPanel:
    """Pressing Food while its timer runs: how long is left, add time, or cancel."""

    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root, bg=WARN)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        inner = tk.Frame(w, bg=PANEL, padx=px(16), pady=px(12))
        inner.pack(padx=2, pady=2)
        head = tk.Frame(inner, bg=PANEL)
        head.pack(fill="x")
        self.title = tk.Label(head, text="", font=(FONT, 12, "bold"), fg=TEXT, bg=PANEL, anchor="w")
        self.title.pack(side="left")
        close = tk.Label(head, text="✕", font=(FONT, 10), fg=MUTED, bg=PANEL, cursor="hand2", padx=4)
        close.pack(side="right", anchor="n")
        close.bind("<Button-1>", lambda e: self.close())
        bar = tk.Frame(inner, bg=PANEL)
        bar.pack(fill="x", pady=(10, 0))
        for m in food.EXTRA_MINUTES:
            button(bar, f"+{m} min", lambda m=m: self.add(m), size=10).pack(side="left", padx=(0, 6))
        button(bar, "Cancel", self.cancel, size=10).pack(side="left", padx=(12, 0))
        self.refresh()
        beside_button(app, w)

    def refresh(self):
        if self.win.winfo_exists():
            self.title.config(text=f"Food: {food.label(self.app.food_left())}")

    def add(self, minutes):
        self.app.food_extend(minutes)
        self.close()

    def cancel(self):
        self.app.food_set(None)
        self.close()

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()


class FoodHere:
    """The Food timer ran out: a big note in the middle of the button's monitor, no sound. Add more time if it's late."""

    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root, bg=WARN)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        inner = tk.Frame(w, bg=PANEL, padx=px(96), pady=px(64))
        inner.pack(padx=px(6), pady=px(6))
        tk.Label(inner, text="Your order is here", font=(FONT, 64, "bold"), fg=TEXT, bg=PANEL).pack()
        tk.Label(inner, text="Still on its way? Give it a few more minutes.", font=(FONT, 18), fg=MUTED,
                 bg=PANEL).pack(pady=(px(10), px(40)))
        bar = tk.Frame(inner, bg=PANEL)
        bar.pack()
        for m in food.EXTRA_MINUTES:
            b = button(bar, f"+{m} min", lambda m=m: self.add(m), size=20)
            b.config(padx=px(28), pady=px(14))
            b.pack(side="left", padx=px(8))
        b = button(bar, "Got it", self.done, primary=True, size=20)
        b.config(padx=px(36), pady=px(14))
        b.pack(side="left", padx=(px(32), 0))
        w.update_idletasks()
        root = app.root
        mons = winapi.monitors()
        mon = next((m for m in mons if m.contains(root.winfo_x() + root.winfo_width() // 2,
                                                   root.winfo_y() + root.winfo_height() // 2)),
                   placement.find(mons, None))
        ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
        w.geometry(placement.geometry(mon.x + (mon.w - ww) // 2, mon.y + (mon.h - wh) // 2))
        w.lift()

    def add(self, minutes):
        self.app.food_extend(minutes)
        self.close()

    def done(self):
        self.app.food_set(None)
        self.close()

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()


class BoredPanel:
    """Bored? Three quick ideas in a small panel beside the button - no lock - and the one you pick runs right there.

    The press is on the record the moment the panel opens; picking an idea adds it to that event, and
    closing without picking leaves it as just a press. Sudoku and music open something else; every other
    idea grows the panel into an activity (a timer, a text box, a friend to text, a glass of water) that
    ends with Done or Stop, and how it went lands on the same event. The panel never locks anything and
    the ✕ closes it at any point - mid-activity that counts as stopping early.
    """

    FAREWELL_MS = 2500
    WIDTH, WIDE = 340, 380
    NOTES_PER_PAGE = 6

    def __init__(self, app):
        self.app = app
        self.event = app.log.record_bored()
        self.shown = []
        self.key = None            # the activity running, once you have picked one
        self.text = ""
        self.countdown = None
        self.opened_at = None
        self.ended = False
        self.follow_up = None      # a question to ask when a timer ends with Done (outside, read)
        self.on_tick = None        # (elapsed, left) -> (big text, small text), for the stretch routine
        self._tick_job = None
        w = self.win = tk.Toplevel(app.root, bg=CALM)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        self.inner = tk.Frame(w, bg=PANEL, padx=px(16), pady=px(12))
        self.inner.pack(padx=2, pady=2)
        self.show_ideas()

    # -- the panel's shape

    def clear(self, width=WIDTH):
        for child in self.inner.winfo_children():
            child.destroy()
        tk.Frame(self.inner, bg=PANEL, width=px(width), height=1).pack()  # keeps the panel one width

    def place(self):
        """Back beside the button after the panel changes size, so it never runs off the screen."""
        if self.win.winfo_exists():
            beside_button(self.app, self.win)

    def head(self, title):
        head = tk.Frame(self.inner, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text=title, font=(FONT, 12, "bold"), fg=TEXT, bg=PANEL, anchor="w",
                 wraplength=px(self.WIDE - 40), justify="left").pack(side="left")
        close = tk.Label(head, text="✕", font=(FONT, 10), fg=MUTED, bg=PANEL, cursor="hand2", padx=4)
        close.pack(side="right", anchor="n")
        close.bind("<Button-1>", lambda e: self.close())

    def note(self, text, top=2, bottom=8, fg=MUTED, size=10):
        tk.Label(self.inner, text=text, font=(FONT, size), fg=fg, bg=PANEL, anchor="w", justify="left",
                 wraplength=px(self.WIDE - 10)).pack(fill="x", pady=(top, bottom))

    def bar(self):
        bar = tk.Frame(self.inner, bg=PANEL)
        bar.pack(fill="x", pady=(8, 0))
        return bar

    def entry(self, default="", width=40):
        e = tk.Entry(self.inner, width=width, font=(FONT, 11), **FIELD)
        if default:
            e.insert(0, default)
        e.pack(fill="x", ipady=4)
        e.focus_set()
        e.bind("<Escape>", lambda ev: self.close())
        return e

    # -- picking

    def show_ideas(self):
        self.clear()
        self.head("Bored? Pick one thing for five minutes.")
        self.note("Something small and real. Scrolling doesn't count.")
        self.shown = pick_ideas(bored_ideas(self.app.config), avoid=self.shown)
        for text in self.shown:
            row = tk.Label(self.inner, text=text, font=(FONT, 11), fg=TEXT, bg=PANEL_HI, anchor="w", padx=px(12),
                           pady=px(8), cursor="hand2")
            row.pack(fill="x", pady=(0, px(4)))
            row.bind("<Button-1>", lambda e, t=text: self.pick(t))
            row.bind("<Enter>", lambda e, r=row: r.config(bg=mix(PANEL_HI, "#FFFFFF", 0.08)))
            row.bind("<Leave>", lambda e, r=row: r.config(bg=PANEL_HI))
        bar = self.bar()
        button(bar, "Show me others", self.show_ideas, size=10).pack(side="right")
        button(bar, "Just log it", self.just_log, size=10).pack(side="left")
        if self.app.log.bored_notes():
            button(bar, "Your notes", lambda: self.show_notes(back=self.show_ideas), size=10).pack(side="left", padx=(6, 0))
        self.place()

    def pick(self, text):
        key = bored_key(text)
        self.app.log.record_choice(self.event, key)
        self.app.refresh_counts()
        if key == "sudoku":
            self.app.open_sudoku()
            return self.farewell("Puzzle's up. Five minutes of that beats five of scrolling.")
        if key == "music":
            return self.farewell(self.app.play_music() or "Music's coming on. Enjoy it.")
        self.start(key, text)

    def start(self, key, text):
        """Run the idea in the panel. Built-in ideas have their own activity; your own get a five-minute timer."""
        self.key, self.text = key, text
        self.opened_at = time.monotonic()
        activities = {
            "write": self.show_write, "stretch": self.show_stretch, "outside": self.show_outside,
            "tidy": self.show_tidy, "read": self.show_read, "practice": self.show_practice,
            "friend": self.show_friend, "water": self.show_water,
        }
        activities.get(key, self.show_custom)()

    def just_log(self):
        self.farewell("Logged. Noticing it counts for something.")

    # -- the activities

    def show_write(self):
        self.clear(self.WIDE)
        self.head("What's on your mind?")
        self.note("Anything at all. Nobody reads this but you.")
        self.box = tk.Text(self.inner, width=40, height=6, font=(FONT, 11), padx=6, pady=4, wrap="word", **FIELD)
        self.box.pack(fill="x")
        self.box.focus_set()
        bar = self.bar()
        button(bar, "Save", self.save_write, primary=True, size=10).pack(side="right")
        notes = self.app.log.bored_notes()
        if notes:
            button(bar, f"Your notes ({len(notes)})", lambda: self.show_notes(back=self.show_write), size=10).pack(side="left")
        self.place()

    def save_write(self):
        text = self.box.get("1.0", "end").strip()
        if not text:
            self.box.focus_set()
            return
        self.app.log.record_note(self.event, text)
        self.end(True)

    def show_notes(self, offset=0, back=None):
        """Everything you have written down, newest first, a page at a time, with a Delete on each."""
        back = back or self.show_ideas
        notes = self.app.log.bored_notes()
        self.clear(self.WIDE)
        self.head("Your notes")
        if not notes:
            self.note("Nothing saved yet. Pick \"Write down what's on your mind\" and it lands here.", bottom=4)
        offset = max(0, min(offset, max(0, len(notes) - 1)))
        for t, e in notes[offset:offset + self.NOTES_PER_PAGE]:
            row = tk.Frame(self.inner, bg=PANEL_HI, padx=px(10), pady=px(6))
            row.pack(fill="x", pady=(0, px(4)))
            top = tk.Frame(row, bg=PANEL_HI)
            top.pack(fill="x")
            tk.Label(top, text=f"{t:%a %d %b, %I:%M %p}".replace(" 0", " "), font=(FONT, 8), fg=MUTED,
                     bg=PANEL_HI, anchor="w").pack(side="left")
            delete = tk.Label(top, text="Delete", font=(FONT, 8), fg=MUTED, bg=PANEL_HI, cursor="hand2")
            delete.pack(side="right")
            delete.bind("<Button-1>", lambda ev, e=e, o=offset: self.delete_note(e, o, back))
            delete.bind("<Enter>", lambda ev, d=delete: d.config(fg=BAD))
            delete.bind("<Leave>", lambda ev, d=delete: d.config(fg=MUTED))
            tk.Label(row, text=e["note"], font=(FONT, 10), fg=TEXT, bg=PANEL_HI, anchor="w", justify="left",
                     wraplength=px(self.WIDE - 30)).pack(fill="x", pady=(2, 0))
        bar = self.bar()
        button(bar, "Back", back, size=10).pack(side="right")
        if offset + self.NOTES_PER_PAGE < len(notes):
            button(bar, "Older", lambda: self.show_notes(offset + self.NOTES_PER_PAGE, back), size=10).pack(side="left")
        if offset > 0:
            button(bar, "Newer", lambda: self.show_notes(max(0, offset - self.NOTES_PER_PAGE), back), size=10).pack(
                side="left", padx=(6, 0))
        if len(notes) > self.NOTES_PER_PAGE:
            tk.Label(bar, text=f"{offset + 1}-{min(offset + self.NOTES_PER_PAGE, len(notes))} of {len(notes)}",
                     font=(FONT, 9), fg=MUTED, bg=PANEL).pack(side="left", padx=(10, 0))
        self.place()

    def delete_note(self, event, offset, back):
        self.app.log.record_note(event, "")
        self.show_notes(offset, back)

    def show_stretch(self):
        self.now_label = None
        self.run_timer("Stretch for 2 minutes", activity_seconds("stretch"),
                       lines=[f"Six stretches, twenty seconds each: {', '.join(s.lower() for s in STRETCHES)}."],
                       extra=self.stretch_names)
        self.on_tick = self.stretch_tick
        self.tick()

    def stretch_names(self, body):
        self.now_label = tk.Label(body, text="", font=(FONT, 15, "bold"), fg=TEXT, bg=PANEL, anchor="w")
        self.now_label.pack(fill="x", pady=(6, 0))
        self.next_label = tk.Label(body, text="", font=(FONT, 10), fg=MUTED, bg=PANEL, anchor="w")
        self.next_label.pack(fill="x")

    def stretch_tick(self, elapsed, left):
        at = stretch_at(elapsed)
        if at is None:
            return "0", ""
        i, name, nxt, in_this = at
        if self.now_label and self.now_label.winfo_exists():
            self.now_label.config(text=f"Now: {name}")
            self.next_label.config(text=f"Next: {nxt}" if nxt else "Last one.")
        return str(int(math.ceil(in_this))), f"{i + 1} of {len(STRETCHES)}  ·  {clock_text(left)} in all"

    def show_outside(self):
        self.follow_up = lambda: self.ask_text("What did you notice?", "see, hear, feel - one line is plenty")
        self.run_timer("Step outside for 5 minutes", activity_seconds("outside"),
                       lines=["Notice 3 things: something you see, hear, and feel.", "The timer keeps going while you're out."])

    def show_tidy(self):
        self.surface = random.choice(SURFACES)

        def extra(body):
            self.surface_label = tk.Label(body, text="", font=(FONT, 15, "bold"), fg=TEXT, bg=PANEL, anchor="w",
                                          wraplength=px(self.WIDE - 10), justify="left")
            self.surface_label.pack(fill="x", pady=(6, 4))
            button(body, "Different one", self.other_surface, size=10).pack(anchor="w")

        self.run_timer("Tidy one surface", activity_seconds("tidy"),
                       lines=["Five minutes, one spot. Not the whole room."], extra=extra)
        self.other_surface(keep=True)

    def other_surface(self, keep=False):
        if not keep:
            self.surface = random.choice([s for s in SURFACES if s != self.surface])
        self.surface_label.config(text=f"Clear {self.surface}.")

    def show_read(self):
        self.follow_up = self.ask_pages
        self.run_timer("Read a few pages", activity_seconds("read"),
                       lines=["Ten minutes. A real book or an article you've been meaning to read, not a feed."])

    def show_practice(self):
        self.clear(self.WIDE)
        self.head("Practice something you're learning")
        self.note("What are you practicing?")
        self.box = self.entry(self.app.log.last_note("practice"))
        self.box.bind("<Return>", lambda e: self.start_practice())
        bar = self.bar()
        button(bar, "Start 10 minutes", self.start_practice, primary=True, size=10).pack(side="right")
        self.place()

    def start_practice(self):
        what = self.box.get().strip()
        if what:
            self.app.log.record_note(self.event, what)
        self.run_timer(f"Practice: {what}" if what else "Practice", activity_seconds("practice"),
                       lines=["Ten minutes on it. Slow and deliberate beats fast and sloppy."])

    def show_custom(self):
        self.run_timer(self.text, activity_seconds(self.key),
                       lines=["Five minutes on it. The timer keeps going if you step away."])

    def show_friend(self):
        self.clear(self.WIDE)
        self.head("Text a friend")
        who, msg, friends = friend_pick(self.app.config)
        self.message = msg
        self.note(f"Pick up your phone and text {who}:", bottom=4)
        tk.Label(self.inner, text=f"“{msg}”", font=(FONT, 12, "italic"), fg=TEXT, bg=PANEL_HI, padx=px(12), pady=px(10),
                 wraplength=px(self.WIDE - 40), justify="left", anchor="w").pack(fill="x")
        if not friends:
            self.note("Tip: add your people in Settings (right-click the button).", top=6, bottom=0, size=9)
        row = tk.Frame(self.inner, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        button(row, "Copy", self.copy_message, size=10).pack(side="left")
        button(row, "Someone else" if len(friends) > 1 else "Different message", self.show_friend, size=10).pack(
            side="left", padx=(6, 0))
        bar = self.bar()
        button(bar, "I texted them", lambda: self.end(True), primary=True, size=10).pack(side="right")
        self.place()

    def copy_message(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.message)
        self.end(True, line="Copied. Go send it.")

    def show_water(self):
        self.clear()
        self.head("Drink a glass of water")
        tk.Label(self.inner, text="Go get a glass. A full one.", font=(FONT, 14), fg=TEXT, bg=PANEL, anchor="w").pack(
            fill="x", pady=(8, 2))
        glasses = self.app.log.glasses_today()
        self.note(f"{plural(glasses, 'glass')} today from here so far." if glasses else "First one today.", bottom=0)
        bar = self.bar()
        button(bar, "Done, I drank it", self.drank, primary=True, size=10).pack(side="right")
        self.place()

    def drank(self):
        n = self.app.log.glasses_today() + 1
        self.end(True, line=f"That's {plural(n, 'glass')} today. Hydrated and a little less bored.")

    # -- timers

    def run_timer(self, title, seconds, lines=(), extra=None):
        """A timed activity: guidance, a big countdown read from the clock, and Pause, Stop and Done."""
        self.clear(self.WIDE)
        self.head(title)
        body = tk.Frame(self.inner, bg=PANEL)
        body.pack(fill="x", pady=(4, 0))
        for line in lines:
            tk.Label(body, text=line, font=(FONT, 10), fg=MUTED, bg=PANEL, anchor="w", justify="left",
                     wraplength=px(self.WIDE - 10)).pack(fill="x", pady=(2, 0))
        if extra:
            extra(body)
        self.clock = tk.Label(self.inner, text="", font=(FONT, 40, "bold"), fg=GOOD, bg=PANEL)
        self.clock.pack(pady=(px(8), 0))
        self.clock_sub = tk.Label(self.inner, text="", font=(FONT, 9), fg=MUTED, bg=PANEL)
        self.clock_sub.pack()
        bar = self.bar()
        button(bar, "Done", lambda: self.end(True), primary=True, size=10).pack(side="right")
        button(bar, "Stop", lambda: self.end(False), size=10).pack(side="right", padx=(0, 6))
        self.pause_btn = button(bar, "Pause", self.toggle_pause, size=10)
        self.pause_btn.pack(side="left")
        self.countdown = Countdown(seconds)
        self.on_tick = None
        self.tick()
        self.place()

    def toggle_pause(self):
        if self.countdown.paused:
            self.countdown.resume()
            self.pause_btn.config(text="Pause")
            self.tick()
        else:
            self.countdown.pause()
            self.pause_btn.config(text="Resume")
            self.clock_sub.config(text="Paused. The clock waits for you.")

    def tick(self):
        if self._tick_job:
            self.win.after_cancel(self._tick_job)
            self._tick_job = None
        if self.ended or not self.win.winfo_exists() or not self.countdown or self.countdown.paused:
            return
        left = self.countdown.remaining()
        big, small = (self.on_tick(self.countdown.elapsed(), left) if self.on_tick else (clock_text(left), ""))
        self.clock.config(text=big)
        self.clock_sub.config(text=small)
        if left <= 0:
            return self.end(True)
        self._tick_job = self.win.after(250, self.tick)

    def seconds_spent(self):
        if self.countdown:
            return self.countdown.elapsed()
        return time.monotonic() - self.opened_at if self.opened_at else 0

    # -- ending

    def end(self, done, line=None):
        """Record how it went, then a follow-up question (Done only) or the goodbye line."""
        if self.ended:
            return
        self.ended = True
        if self._tick_job:
            self.win.after_cancel(self._tick_job)
            self._tick_job = None
        self.app.log.record_outcome(self.event, done, self.seconds_spent())
        self.app.refresh_counts()
        if done and self.follow_up:
            return self.follow_up()
        self.farewell(line or (finish_line(self.key) if done else random.choice(STOP_LINES)))

    def ask_text(self, prompt, hint):
        """One optional line, saved as the note."""
        self.clear(self.WIDE)
        self.head(prompt)
        self.note(hint)
        box = self.entry()

        def save():
            self.app.log.record_note(self.event, box.get())
            self.farewell(finish_line(self.key))

        box.bind("<Return>", lambda e: save())
        bar = self.bar()
        button(bar, "Save", save, primary=True, size=10).pack(side="right")
        button(bar, "Skip", lambda: self.farewell(finish_line(self.key)), size=10).pack(side="right", padx=(0, 6))
        self.place()

    def ask_pages(self):
        self.clear(self.WIDE)
        self.head("How many pages?")
        self.note("Roughly is fine.")
        box = tk.Spinbox(self.inner, from_=0, to=999, width=6, font=(FONT, 12), **FIELD, buttonbackground=PANEL_HI)
        box.pack(anchor="w")
        box.focus_set()

        def save():
            try:
                n = int(box.get())
            except ValueError:
                n = 0
            if n > 0:
                self.app.log.record_amount(self.event, n)
            self.farewell(finish_line(self.key))

        box.bind("<Return>", lambda e: save())
        bar = self.bar()
        button(bar, "Save", save, primary=True, size=10).pack(side="right")
        button(bar, "Skip", lambda: self.farewell(finish_line(self.key)), size=10).pack(side="right", padx=(0, 6))
        self.place()

    def farewell(self, line):
        self.clear()
        tk.Label(self.inner, text=line, font=(FONT, 12), fg=TEXT, bg=PANEL, anchor="w", wraplength=px(330),
                 justify="left").pack(fill="x", pady=(2, 2))
        self.place()
        self.win.after(self.FAREWELL_MS, self.close)

    def close(self):
        if not self.win.winfo_exists():
            return
        if self.key and not self.ended:  # closed mid-activity: that is stopping early
            self.ended = True
            self.app.log.record_outcome(self.event, False, self.seconds_spent())
            self.app.refresh_counts()
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
        hotkeys = [
            "Ctrl+Alt+U also triggers the lock from anywhere." if app.hotkey_ok else
            "Ctrl+Alt+U is taken by another app, so only the button works.",
            "Ctrl+Alt+B opens the Bored ideas." if app.bored_hotkey_ok else
            "Ctrl+Alt+B is taken by another app, so only the Bored button works.",
        ]
        tk.Label(left, text="\n".join(hotkeys), font=(FONT, 10), fg=MUTED, bg=BG, anchor="w",
                 justify="left").pack(fill="x", pady=(6, 0))
        upd = tk.Frame(left, bg=BG)
        upd.pack(fill="x", pady=(10, 0))
        self.update_label = tk.Label(upd, text="", font=(FONT, 10), fg=MUTED, bg=BG, anchor="w",
                                     wraplength=px(300), justify="left")
        self.update_label.pack(side="left", fill="x", expand=True)
        button(upd, "Check for updates", app.check_updates_now, size=10).pack(side="right")
        self._watch_updates()

        # Right: the lock itself
        tk.Label(right, text="The lock", font=(FONT, 13, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        label(right, f"Lock length (minutes, 1-{MAX_LOCK_MINUTES})", top=6)
        self.minutes = tk.Spinbox(right, from_=1, to=MAX_LOCK_MINUTES, width=6, font=(FONT, 12), **FIELD,
                                  buttonbackground=PANEL_HI)
        self.minutes.delete(0, "end")
        self.minutes.insert(0, str(app.config["lock_minutes"]))
        self.minutes.pack(anchor="w")
        self.escalate = tk.BooleanVar(value=app.config.get("escalate", True))
        tk.Checkbutton(right, text="Longer locks when urges come close together (5, then 10 min)",
                       variable=self.escalate, font=(FONT, 10), fg=TEXT, bg=BG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=TEXT).pack(anchor="w", pady=(4, 0))

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
        tk.Label(third, text="When you're bored", font=(FONT, 13, "bold"), fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        label(third, "Ideas the Bored button offers, three at a time (one per line)", top=6)
        self.bored = tk.Text(third, width=36, height=6, font=(FONT, 11), padx=6, pady=4, **FIELD)
        self.bored.insert("1.0", "\n".join(bored_ideas(app.config)))
        self.bored.pack(anchor="w")
        tk.Label(third, text="\"Play Sudoku\" opens the Sudoku and \"Put music on\" starts Spotify; the rest are nudges. "
                             "Leave it blank for the defaults.",
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

    def _watch_updates(self):
        if self.win.winfo_exists():
            u = self.app.updater
            text = (f"Update ready: {u.ready}. It installs itself once nothing's open and you've stepped away, "
                    "or right now from the button's menu.") if u.ready else u.status
            self.update_label.config(text="Updates: " + text, fg=GOOD if u.ready else MUTED)
            self.win.after(1000, self._watch_updates)

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
            t.geometry(placement.geometry(m.x + (m.w - size) // 2, m.y + (m.h - size) // 2, size, size))
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
        cfg["escalate"] = bool(self.escalate.get())
        cfg["plan"] = self.plan.get().strip()
        cfg["block_apps"] = [x.strip() for x in self.block.get("1.0", "end").splitlines() if x.strip()]
        try:
            cfg["block_minutes"] = max(0, min(240, int(self.block_minutes.get())))
        except ValueError:
            pass
        ideas = [x.strip() for x in self.bored.get("1.0", "end").splitlines() if x.strip()]
        cfg["bored_ideas"] = [] if ideas == [text for _, text in BORED_IDEAS] else ideas  # the defaults stay defaults
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
    W, H = 196, 78     # the URGE button
    BW, GAP = 76, 4    # the smaller Bored button beside it, and the seam between the two
    FW = 76            # the Food timer button after Bored
    BORDER = 2         # the bright outline that makes it findable on a dark screen
    ON_TOP_SECONDS = 2  # how often it checks that nothing has covered it

    def __init__(self, log=None, sudoku_log=None, hotkey=True):
        self.config = load_config()
        self.log = log or EventLog()
        self.sudoku = sudoku_log or SudokuLog()
        self.sudoku_views = []  # every board on screen, so a sync can redraw them
        self.lock = None
        self.settings = None
        self.sudoku_win = None
        self.bored_panel = None
        self.heads_up_key = None

        root = self.root = tk.Tk()
        theme.init_scale(root)
        root.title("Urge Button")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BG, highlightthickness=px(self.BORDER), highlightbackground=ACCENT_BRIGHT,
                       highlightcolor=ACCENT_BRIGHT)

        self.place_button()

        # One window, two buttons: URGE on the left, Bored on the right. They move and dock together.
        self.face = tk.Frame(root, bg=ACCENT, cursor="hand2", width=px(self.W), height=px(self.H))
        self.face.pack(side="left", fill="y")
        self.face.pack_propagate(False)
        self.title = tk.Label(self.face, text="URGE", font=(FONT, 18, "bold"), fg=TEXT, bg=ACCENT)
        self.sub = tk.Label(self.face, text="", font=(FONT, 9), fg=TEXT, bg=ACCENT)
        self.title.pack(pady=(px(8), 0))
        self.sub.pack()
        self.bored_face = tk.Frame(root, bg=CALM, cursor="hand2", width=px(self.BW), height=px(self.H))
        self.bored_face.pack(side="left", fill="y", padx=(px(self.GAP), 0))
        self.bored_face.pack_propagate(False)
        self.bored_title = tk.Label(self.bored_face, text="Bored", font=(FONT, 11, "bold"), fg=TEXT, bg=CALM)
        self.bored_sub = tk.Label(self.bored_face, text="", font=(FONT, 8), fg=TEXT, bg=CALM)
        self.bored_title.pack(pady=(px(14), 0))
        self.bored_sub.pack()
        self.food_face = tk.Frame(root, bg=WARN, cursor="hand2", width=px(self.FW), height=px(self.H))
        self.food_face.pack(side="left", fill="y", padx=(px(self.GAP), 0))
        self.food_face.pack_propagate(False)
        self.food_title = tk.Label(self.food_face, text="Food", font=(FONT, 11, "bold"), fg=BG, bg=WARN)
        self.food_sub = tk.Label(self.food_face, text="", font=(FONT, 8), fg=BG, bg=WARN)
        self.food_title.pack(pady=(px(14), 0))
        self.food_sub.pack()
        food_widgets = (self.food_face, self.food_title, self.food_sub)
        for wdg in food_widgets:
            wdg.bind("<Enter>", lambda e: [x.config(bg=mix(WARN, "#FFFFFF", 0.15)) for x in food_widgets])
            wdg.bind("<Leave>", lambda e: [x.config(bg=WARN) for x in food_widgets])
        self.food_panel = None
        self.food_here = None
        bored_widgets = (self.bored_face, self.bored_title, self.bored_sub)
        for wdg in bored_widgets:
            wdg.bind("<Enter>", lambda e: [x.config(bg=mix(CALM, "#FFFFFF", 0.08)) for x in bored_widgets])
            wdg.bind("<Leave>", lambda e: [x.config(bg=CALM) for x in bored_widgets])

        # Settings gear in the corner; its clicks never start a lock or a drag.
        gear = tk.Label(self.face, text="⚙", font=("Segoe UI Symbol", 11), fg=TEXT, bg=ACCENT, cursor="hand2")
        gear.place(relx=1.0, x=-px(4), y=px(1), anchor="ne")
        self.update_dot = tk.Label(self.face, text="●", font=(FONT, 8), fg=GOOD, bg=ACCENT, cursor="hand2")
        self.update_dot.bind("<Button-1>", lambda e: self.restart_to_update())
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.bind("<Enter>", lambda e: gear.config(fg="#C9CCFF"))
        gear.bind("<Leave>", lambda e: gear.config(fg=TEXT))

        menu = self.menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="Progress", command=self.show_progress)
        menu.add_command(label="Sudoku", command=self.open_sudoku)
        menu.add_command(label="Log an urge I handled on my own", command=lambda: LogOwnWindow(self))
        menu.add_command(label="I'm bored", command=self.bored)
        menu.add_separator()
        menu.add_command(label="Settings", command=self.open_settings)
        menu.add_command(label="Quit", command=root.destroy)

        for wdg in (self.face, self.title, self.sub):
            wdg.bind("<ButtonPress-1>", self._press)
            wdg.bind("<B1-Motion>", self._drag)
            wdg.bind("<ButtonRelease-1>", self._release)
            wdg.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        for wdg in bored_widgets:
            wdg.bind("<ButtonPress-1>", self._press)
            wdg.bind("<B1-Motion>", self._drag)
            wdg.bind("<ButtonRelease-1>", lambda e: self._release(e, self.bored))
            wdg.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        for wdg in food_widgets:
            wdg.bind("<ButtonPress-1>", self._press)
            wdg.bind("<B1-Motion>", self._drag)
            wdg.bind("<ButtonRelease-1>", lambda e: self._release(e, self.food_press))
            wdg.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        self.hotkey = winapi.Hotkey((("U", "urge"), ("B", "bored")))
        registered = self.hotkey.start() if hotkey else {}
        self.hotkey_ok = registered.get("urge", False)
        self.bored_hotkey_ok = registered.get("bored", False)

        # Closing chosen apps during a lock and the cooldown after it
        self.app_blocker = AppBlocker()
        self._block_loop()

        # Self-update from GitHub (like Rift Pen): check on start and every 30 minutes, restart when it's quiet
        self.updater = Updater(Path(__file__).resolve().parent)
        self._update_results = queue.Queue()
        self._restart_watch = False
        if hotkey:  # previews never touch git
            self.root.after(20_000, self._check_updates)

        # Sync with the phone through the private data repo
        self.online = hotkey  # previews run offline
        self.sync_status = "Not synced yet"
        self._sync_job = None
        self._syncing = False
        self._sync_again = False
        self._sync_results = queue.Queue()
        self.log.on_change = lambda: self.schedule_sync(3000)
        # Sudoku moves come thick and fast, so they wait a little longer; a game starting or ending goes out right away
        self.sudoku.on_change = lambda notify: self.schedule_sync(1000 if notify == "now" else 15_000)
        if self.online:
            self.schedule_sync(1500)
            self._sync_every()

        self._poll_hotkey()
        self._tick_counts()
        self._keep_on_top()
        self._food_tick()

    # -- the Food timer

    def food_left(self):
        return food.left(self.config.get("food_until"), time.time())

    def food_set(self, until):
        self.config["food_until"] = until
        self.save_config()
        self._food_tick(repeat=False)

    def food_extend(self, minutes):
        self.food_set(food.extend(self.config.get("food_until"), time.time(), minutes))

    def food_press(self):
        """Idle: start the 25 minutes. Running: how long is left, with add-time and cancel."""
        for w in (self.food_panel, self.food_here):
            if w and w.win.winfo_exists():
                w.win.lift()
                return
        if self.food_left() is None:
            self.food_extend(food.DEFAULT_MINUTES)
        else:
            self.food_panel = FoodPanel(self)

    def _food_tick(self, repeat=True):
        left = self.food_left()
        self.food_sub.config(text=food.label(left))
        if self.food_panel:
            self.food_panel.refresh()
        if left == 0 and not (self.food_here and self.food_here.win.winfo_exists()):
            if self.food_panel:
                self.food_panel.close()
            self.food_here = FoodHere(self)
        if repeat:
            self.root.after(5000, self._food_tick)

    def _keep_on_top(self):
        """Windows can leave an always-on-top window under an ordinary one (seen under Discord, 2026-10-13), so
        when another app's window is over the middle of the button, raise it again. A lock covers it on purpose."""
        if self.lock is None:
            x, y = self.root.winfo_x() + self.width() // 2, self.root.winfo_y() + self.height() // 2
            if self.root.winfo_containing(x, y) is None:
                self.root.attributes("-topmost", False)
                self.root.attributes("-topmost", True)
                self.root.lift()
        self.root.after(self.ON_TOP_SECONDS * 1000, self._keep_on_top)

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
        try:
            if self._sync_job:
                self.root.after_cancel(self._sync_job)
            self._sync_job = self.root.after(delay, self.sync_now)
        except tk.TclError:
            pass  # the app is closing; the next start syncs

    def sync_now(self):
        self._sync_job = None
        if self._syncing:
            self._sync_again = True
            return
        self._syncing = True
        snapshot = self.log.shared()
        sudoku_snapshot = self.sudoku.shared()
        repo = self.config.get("sync_repo") or sync.DEFAULT_REPO
        token = self.config.get("sync_token") or None

        def work():
            try:
                tok = token or sync.gh_cli_token()
                if not tok:
                    raise sync.SyncError("no GitHub token yet - add one in Settings")
                self._sync_results.put(("events", sync.sync(snapshot, sync.GitHubFile(repo, tok))))
                self._sync_results.put(("sudoku", sync.sync_sudoku(sudoku_snapshot, sync.GitHubFile(repo, tok, sync.SUDOKU_PATH))))
                self._sync_results.put(("done", None))
            except Exception as e:  # never let a network problem take the app down
                self._sync_results.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _sync_done(self, kind, value):
        if kind == "events":
            if self.log.apply_shared(value):
                self.refresh_counts()
            return
        if kind == "sudoku":
            if self.sudoku.apply_shared(value):
                for view in list(self.sudoku_views):
                    view.refresh()
                if self.sudoku_win and self.sudoku_win.win.winfo_exists():
                    self.sudoku_win.render_stats()
            return
        self._syncing = False
        if kind == "done":
            self.sync_status = f"Synced at {datetime.now():%I:%M %p}".replace(" 0", " ")
        else:
            self.sync_status = f"Sync problem: {value}"
        if self._sync_again:
            self._sync_again = False
            self.schedule_sync(500)

    def _poll_hotkey(self):
        while not self.hotkey.presses.empty():
            name = self.hotkey.presses.get_nowait()
            (self.bored if name == "bored" else self.trigger)()
        while not self._sync_results.empty():
            self._sync_done(*self._sync_results.get_nowait())
        while not self._update_results.empty():
            self._update_done(self._update_results.get_nowait())
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
        self.bored_sub.config(text=f"today {self.log.today(bored=True)}")

    def save_config(self):
        save_json(CONFIG_PATH, self.config)

    def play_music(self):
        """Open Spotify (your playlist from Settings) and press play once it's up. Returns a problem line, or None."""
        if not self.online:
            return None  # previews never launch anything
        try:
            os.startfile(self.config.get("spotify_uri") or "spotify:")
        except OSError:
            return "Couldn't open Spotify - is it installed?"
        self.root.after(4000, winapi.press_media_play)  # Spotify opens paused; give it a moment, then press play
        return None

    # -- self-update

    def _check_updates(self, repeat=True):
        threading.Thread(target=lambda: self._update_results.put(self.updater.check()), daemon=True).start()
        if repeat:
            self.root.after(CHECK_SECONDS * 1000, self._check_updates)

    def check_updates_now(self):
        self.updater.status = "Checking..."
        self._check_updates(repeat=False)

    def _update_done(self, ready):
        if not ready:
            return
        self.update_dot.place(relx=0.0, x=px(6), y=px(3), anchor="nw")
        label = f"Restart to update ({ready[:40]})"
        if getattr(self, "_update_menu_label", None) != label:
            if getattr(self, "_update_menu_label", None):
                self.menu.delete(0, 1)
            self.menu.insert_command(0, label=label, command=self.restart_to_update)
            self.menu.insert_separator(1)
            self._update_menu_label = label
        if not self._restart_watch:
            self._restart_watch = True
            self.root.after(RESTART_POLL_SECONDS * 1000, self._auto_restart)

    def open_windows(self):
        """Everything on screen besides the button: a lock, Sudoku, Settings, Progress, a heads-up."""
        return [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]

    def _auto_restart(self):
        """Apply a downloaded update the moment nothing's open and the computer has been left alone."""
        if restart_allowed(self.updater.ready, self.open_windows(), winapi.idle_seconds()):
            self.restart_to_update()
            return
        self.root.after(RESTART_POLL_SECONDS * 1000, self._auto_restart)

    def restart_to_update(self):
        if self.lock is not None:
            return  # never in the middle of a lock; the update also applies at the next start
        import subprocess
        subprocess.Popen([str(winapi.pythonw()), str(winapi.SCRIPT), "--restarted"], cwd=str(winapi.SCRIPT.parent),
                         creationflags=0x00000008 | 0x00000200)
        self.root.destroy()

    def open_settings(self):
        if self.settings and self.settings.win.winfo_exists():
            self.settings.win.lift()
            self.settings.win.focus_force()
        else:
            self.settings = SettingsWindow(self)

    def open_sudoku(self):
        if self.sudoku_win and self.sudoku_win.win.winfo_exists():
            self.sudoku_win.win.lift()
            self.sudoku_win.win.focus_force()
        else:
            self.sudoku_win = SudokuWindow(self)

    def width(self):
        """The whole floating window: URGE, the seam, and Bored."""
        return px(self.W + self.GAP + self.BW + self.GAP + self.FW) + 2 * px(self.BORDER)

    def height(self):
        return px(self.H) + 2 * px(self.BORDER)

    def place_button(self):
        """Put the button where the config says, falling back to the main monitor if that spot is gone."""
        w, h = self.width(), self.height()
        mons = winapi.monitors()
        cfg = self.config
        x, y = cfg.get("button_x"), cfg.get("button_y")
        anchor = cfg.get("button_anchor") or "bottom-right"
        if anchor == "custom" and x is not None and y is not None and placement.on_screen(mons, x, y, w, h):
            x, y = placement.clamp(mons, x, y, w, h)
        else:
            if anchor == "custom":
                anchor = "bottom-right"
            mon = placement.find(mons, cfg.get("button_monitor"))
            x, y = placement.anchor_position(mon, w, h, anchor, margin=px(24))
        self.root.geometry(placement.geometry(x, y, w, h))

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
            self.root.geometry(placement.geometry(wx + dx, wy + dy))

    def _release(self, e, action=None):
        if self._moved:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            cfg = self.config
            cfg["button_x"], cfg["button_y"], cfg["button_anchor"] = x, y, "custom"
            here = [m for m in winapi.monitors() if m.contains(x + self.width() // 2, y + self.height() // 2)]
            if here:
                cfg["button_monitor"] = here[0].name
            self.save_config()
        else:
            (action or self.trigger)()

    def trigger(self, preview=False):
        if self.lock is not None:
            return
        minutes = base = self.config["lock_minutes"]
        recent = self.log.recent_locks()
        if self.config.get("escalate", True):
            minutes = cluster_minutes(base, recent)
        event = self.log.record_press(minutes)
        if self.config.get("block_apps") and not preview:
            cooldown = max(0, int(self.config.get("block_minutes") or 0))
            self.app_blocker.start(self.config["block_apps"], (minutes + cooldown) * 60)
            threading.Thread(target=self.app_blocker.tick, daemon=True).start()
        self.refresh_counts()
        note = None
        if minutes > base:
            nth = {1: "Second", 2: "Third"}.get(recent, "Another")
            note = f"{nth} urge in half an hour, so this lock is {minutes} minutes. Clusters are the hard part; you're riding it out."
        self.lock = LockScreen(self, minutes, event, preview=preview, note=note)

    def on_unlock(self):
        self.lock = None
        self.refresh_counts()

    def bored(self):
        """The Bored button: no lock, a few quick ideas, and the press goes on its own record."""
        if self.lock is not None:
            return  # you're in the middle of an urge; that comes first
        if self.bored_panel and self.bored_panel.win.winfo_exists():
            self.bored_panel.win.lift()
            return
        self.bored_panel = BoredPanel(self)
        self.refresh_counts()

    def show_progress(self):
        ProgressWindow(self.root, self.log)


# --------------------------------------------------------------------------- entry


def run_preview(out_dir, stage):
    """Render a screen in a normal window against a throwaway log (no lock, no hook), screenshot it, exit."""
    from PIL import ImageGrab

    out = Path(out_dir)
    app = App(log=fake_log(out / "preview-events.json"), sudoku_log=fake_sudoku_log(out / "preview-sudoku.json"),
              hotkey=False)
    app.save_config = lambda: None  # previews never touch the real settings
    app.config["reasons"] = ["I want my evenings back.", "Future me is proud of every one of these."]
    target = None
    if stage == "progress":
        target = ProgressWindow(app.root, app.log).win
        target.attributes("-topmost", True)
    elif stage in ("sudokuwin", "sudokusolved", "sudokunew"):
        app.open_sudoku()
        target = app.sudoku_win.win
        target.attributes("-topmost", True)
        view = app.sudoku_win.view
        if stage == "sudokusolved":  # finish the half-played puzzle so the "Solved" card shows
            view.game.vals = list(view.game.sol)
            view.after_move()
        elif stage == "sudokunew":
            view.choose()
    elif stage == "logged":
        target = LogOwnWindow(app).win
    elif stage == "settings":
        target = SettingsWindow(app).win
    elif stage == "button":
        target = app.root
    elif stage == "cluster":
        app.lock = None
        app.trigger(preview=True)
        app.lock.win.destroy()
        app.lock = None
        app.trigger(preview=True)
        target = app.lock.win
    elif stage == "headsup":
        target = HeadsUp(app, 21).win
    elif stage == "food":  # the timer running, pressed again
        app.food_set(time.time() + 18 * 60)
        app.food_press()
        target = app.food_panel.win
    elif stage == "foodhere":
        app.food_set(time.time() - 1)
        target = app.food_here.win
    elif stage.startswith("bored"):
        # bored = the ideas; boredwrite / boredstretch / boredtimer (outside) / boredtidy / boredread / boredpractice /
        # boredfriend / boredwater / boredcustom = that activity running; borednotes = your notes; borednoticed and
        # boredpages = the questions after Done; boredpicked = the goodbye line after a finished activity
        app.bored()
        panel = app.bored_panel
        target = panel.win
        which = stage[len("bored"):]
        key = {"timer": "outside", "noticed": "outside", "pages": "read", "picked": "water", "custom": "Juggle"}.get(which, which)
        if which == "notes":
            panel.show_notes()
        elif which:
            panel.start(key, bored_name(key))
            if which in ("noticed", "pages"):
                panel.end(True)
            elif which == "picked":
                panel.drank()  # the goodbye line stays up longer than the screenshot takes
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
    if not winapi.single_instance(wait_seconds=15 if "--restarted" in sys.argv else 0):
        return
    App().root.mainloop()


if __name__ == "__main__":
    main()
