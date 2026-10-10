"""Urge Button - press it when an urge hits; the computer locks for a few minutes.

A small floating button sits on the desktop (or press Ctrl+Alt+U from anywhere).
Pressing it covers every monitor with a lock screen for the configured number of
minutes (default 3), blocks the Windows key / Alt+Tab / Alt+F4 while it is up,
logs the urge, and offers four things to do instead: go for a walk, put on
Spotify, play Sudoku, or reach out to a friend. When the timer ends you rate how
strong the urge was.

Right-click the button for Progress, logging an urge you handled without the
lock, Settings and Quit. Data lives in %APPDATA%\\UrgeButton.

Ctrl+Alt+Del is handled by Windows itself and cannot be blocked - that is the
deliberate hard exit. The lock always ends on its own when the timer runs out.

    pythonw urge_button.py                       run it
    python urge_button.py --install              desktop shortcut + start with Windows
    python urge_button.py --preview DIR STAGE    screenshot a screen without locking
"""

import os
import random
import sys
import tkinter as tk
from pathlib import Path

import placement
import theme
import winapi
from progress import ProgressWindow, fake_log
from sudoku import check as check_sudoku
from sudoku import make_puzzle
from theme import ACCENT, BAD, BG, FONT, GOOD, MUTED, PANEL, PANEL_HI, TEXT, button, px
from urge_log import (
    CONFIG_PATH, MAX_LOCK_MINUTES, OPTIONS, EventLog, clamp_minutes, format_gap, load_config,
    save_json, to_spotify_uri,
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
        self.clock = tk.Label(self.body, text="", font=(FONT, 64, "bold"), fg=ACCENT, bg=BG)
        self.clock.pack(pady=(10, 18))

        self.stage = tk.Frame(self.body, bg=BG)
        self.stage.pack()
        self.show_options()

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

    def show_options(self):
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
        self.clear_stage()
        tk.Label(self.stage, text="How strong was the urge?", font=(FONT, 14), fg=MUTED, bg=BG).pack(pady=(0, 10))
        intensity_picker(self.stage, lambda n: self.app.log.record_intensity(self.event, n),
                         self.event.get("intensity")).pack()
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


class LogOwnWindow:
    """Log an urge you rode out without locking the screen."""

    def __init__(self, app):
        self.app = app
        self.intensity = None
        w = self.win = small_window(app, "Urge Button - Log an urge")
        tk.Label(w, text="Handled one on your own?", font=(FONT, 16, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(w, text="It still counts - logging it keeps the picture honest. How strong was it?",
                 font=(FONT, 10), fg=MUTED, bg=BG).pack(anchor="w", pady=(2, 12))
        intensity_picker(w, self._pick).pack(anchor="w")
        bar = tk.Frame(w, bg=BG)
        bar.pack(fill="x", pady=(16, 0))
        button(bar, "Log it", self.save, primary=True).pack(side="right")
        button(bar, "Cancel", w.destroy).pack(side="right", padx=6)

    def _pick(self, n):
        self.intensity = n

    def save(self):
        self.app.log.record_logged(self.intensity)
        self.app.refresh_counts()
        self.win.destroy()


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        w = self.win = small_window(app, "Urge Button - Settings")

        def label(text):
            tk.Label(w, text=text, font=(FONT, 11), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(10, 2))

        self.build_placement(w)
        tk.Frame(w, bg=PANEL_HI, height=1).pack(fill="x", pady=(16, 4))

        label(f"Lock length (minutes, 1-{MAX_LOCK_MINUTES})")
        self.minutes = tk.Spinbox(w, from_=1, to=MAX_LOCK_MINUTES, width=6, font=(FONT, 12), **FIELD,
                                 buttonbackground=PANEL_HI)
        self.minutes.delete(0, "end")
        self.minutes.insert(0, str(app.config["lock_minutes"]))
        self.minutes.pack(anchor="w")

        label("Spotify link (playlist URL or spotify:playlist:... - blank just opens Spotify)")
        self.spotify = tk.Entry(w, width=56, font=(FONT, 11), **FIELD)
        uri = app.config.get("spotify_uri", "")
        self.spotify.insert(0, "" if uri == "spotify:" else uri)
        self.spotify.pack(anchor="w")

        label("Friends to reach out to (one per line)")
        self.friends = tk.Text(w, width=40, height=6, font=(FONT, 11), padx=6, pady=4, **FIELD)
        self.friends.insert("1.0", "\n".join(app.config.get("friends", [])))
        self.friends.pack(anchor="w")

        self.startup = tk.BooleanVar(value=winapi.starts_with_windows())
        tk.Checkbutton(w, text="Start with Windows", variable=self.startup, font=(FONT, 11), fg=TEXT, bg=BG,
                       selectcolor=PANEL, activebackground=BG, activeforeground=TEXT).pack(anchor="w", pady=(12, 0))
        hotkey = "Ctrl+Alt+U also triggers the lock from anywhere." if app.hotkey_ok else \
            "Ctrl+Alt+U is taken by another app, so only the button works."
        tk.Label(w, text=hotkey, font=(FONT, 10), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(6, 0))

        bar = tk.Frame(w, bg=BG)
        bar.pack(fill="x", pady=(14, 0))
        button(bar, "Save", self.save, primary=True).pack(side="right")
        button(bar, "Cancel", w.destroy).pack(side="right", padx=6)

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
        self._poll_hotkey()
        self._tick_counts()

    def _poll_hotkey(self):
        while not self.hotkey.presses.empty():
            self.hotkey.presses.get_nowait()
            self.trigger()
        self.root.after(150, self._poll_hotkey)

    def _tick_counts(self):
        self.refresh_counts()
        self.root.after(30_000, self._tick_counts)

    def refresh_counts(self):
        since = self.log.since_last()
        gap = "none yet" if since is None else f"{format_gap(since)} ago" if since >= 60 else "just now"
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
    else:
        app.trigger(preview=True)
        target = app.lock.win
        if stage == "finish":
            app.lock.finish()
        elif stage != "options":
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
