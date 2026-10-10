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
    python urge_button.py --preview DIR STAGE    screenshot a screen without locking
"""

import os
import random
import sys
import tkinter as tk
from pathlib import Path

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

        # Centre the content on the primary monitor (the one at 0,0).
        self.body = tk.Frame(self.win, bg=BG)
        if preview:
            self.body.place(relx=0.5, rely=0.5, anchor="center")
        else:
            vx, vy = winapi.virtual_screen()[:2]
            sw, sh = app.root.winfo_screenwidth(), app.root.winfo_screenheight()
            self.body.place(x=-vx + sw // 2, y=-vy + sh // 2, anchor="center")

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

        root = self.root = tk.Tk()
        theme.init_scale(root)
        root.title("Urge Button")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=ACCENT)

        w, h = px(self.W), px(self.H)
        x, y = self.config.get("button_x"), self.config.get("button_y")
        if x is None or y is None or not (0 <= x < root.winfo_vrootwidth() and 0 <= y < root.winfo_vrootheight()):
            x = root.winfo_screenwidth() - w - px(24)
            y = root.winfo_screenheight() - h - px(72)
        root.geometry(f"{w}x{h}+{x}+{y}")

        self.face = tk.Frame(root, bg=ACCENT, cursor="hand2")
        self.face.pack(fill="both", expand=True)
        self.title = tk.Label(self.face, text="URGE", font=(FONT, 16, "bold"), fg=TEXT, bg=ACCENT)
        self.sub = tk.Label(self.face, text="", font=(FONT, 9), fg=TEXT, bg=ACCENT)
        self.title.pack(pady=(px(8), 0))
        self.sub.pack()

        menu = self.menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="Progress", command=self.show_progress)
        menu.add_command(label="Log an urge I handled on my own", command=lambda: LogOwnWindow(self))
        menu.add_separator()
        menu.add_command(label="Settings", command=lambda: SettingsWindow(self))
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
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def _release(self, e):
        if self._moved:
            self.config["button_x"], self.config["button_y"] = self.root.winfo_x(), self.root.winfo_y()
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
    if len(sys.argv) >= 3 and sys.argv[1] == "--preview":
        run_preview(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "options")
        return
    if not winapi.single_instance():
        return
    App().root.mainloop()


if __name__ == "__main__":
    main()
