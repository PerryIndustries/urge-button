"""The Progress window: headline tiles plus charts drawn on Tk canvases (hover any mark for its value)."""

import math
import tkinter as tk
from datetime import timedelta

from theme import (
    ACCENT, ACCENT_SOFT, BG, CHART_BG, FONT, GOOD, GRID, HEAT_HIGH, HEAT_LOW, HEAT_ZERO, MUTED,
    PANEL, TEXT, WARN, button, mix, px,
)
from urge_log import OPTION_NAMES, format_gap

HOURS = ["12a", "1a", "2a", "3a", "4a", "5a", "6a", "7a", "8a", "9a", "10a", "11a",
         "12p", "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p", "10p", "11p"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def hour_range(h):
    return f"{HOURS[h]}-{HOURS[(h + 1) % 24]}"


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class Tip:
    """One floating tooltip per canvas."""

    def __init__(self, canvas):
        self.c = canvas
        self.items = []

    def show(self, x, y, text):
        self.hide()
        t = self.c.create_text(x, y - px(8), text=text, fill=TEXT, font=(FONT, 10), anchor="s", justify="center")
        x0, y0, x1, y1 = self.c.bbox(t)
        width = int(self.c["width"])
        shift = max(0, px(6) - x0) - max(0, x1 - (width - px(6)))
        self.c.move(t, shift, 0)
        r = self.c.create_rectangle(x0 + shift - px(7), y0 - px(4), x1 + shift + px(7), y1 + px(4),
                                    fill="#2E3236", outline="")
        self.c.tag_raise(t)
        self.items = [r, t]

    def hide(self):
        for i in self.items:
            self.c.delete(i)
        self.items = []


def nice_scale(maxv):
    for step in (1, 2, 5, 10, 25, 50, 100, 250):
        if math.ceil(maxv / step) <= 4:
            return step * max(1, math.ceil(maxv / step)), step
    return maxv, maxv


def titled(canvas, title, subtitle):
    canvas.create_text(px(16), px(14), text=title, fill=TEXT, font=(FONT, 12, "bold"), anchor="nw")
    canvas.create_text(px(16), px(36), text=subtitle, fill=MUTED, font=(FONT, 9), anchor="nw")


def bar_chart(c, tip, box, values, xlabels, tips, highlight=(), line=None, line_label=None):
    x, y, w, h = box
    pl, pr, pt, pb = x + px(30), x + w, y, y + h - px(18)
    top, step = nice_scale(max(max(values), max((v for v in (line or []) if v is not None), default=0), 1))

    for v in range(0, int(top) + 1, step):
        yy = pb - v / top * (pb - pt)
        c.create_line(pl, yy, pr, yy, fill=GRID)
        c.create_text(pl - px(6), yy, text=str(v), fill=MUTED, font=(FONT, 8), anchor="e")

    n = len(values)
    bw = (pr - pl) / n
    for i, v in enumerate(values):
        x0, x1 = pl + i * bw, pl + (i + 1) * bw
        tag = f"bar{i}"
        c.create_rectangle(x0, pt, x1, pb, fill=CHART_BG, outline="", tags=tag)
        top_y = pb
        if v > 0:
            top_y = pb - v / top * (pb - pt)
            c.create_rectangle(x0 + 1, top_y, x1 - 1, pb, fill=ACCENT if i in highlight else ACCENT_SOFT,
                               outline="", tags=tag)
        cx = (x0 + x1) / 2
        c.tag_bind(tag, "<Enter>", lambda e, cx=cx, ty=top_y, t=tips[i]: tip.show(cx, min(ty, pb - px(4)), t))
        c.tag_bind(tag, "<Leave>", lambda e: tip.hide())
        if i in xlabels:
            c.create_text(cx, pb + px(4), text=xlabels[i], fill=MUTED, font=(FONT, 8), anchor="n")
    c.create_line(pl, pb, pr, pb, fill=MUTED)

    if line:
        pts = []
        for i, v in enumerate(line):
            if v is not None:
                pts += [pl + (i + 0.5) * bw, pb - v / top * (pb - pt)]
        if len(pts) >= 4:
            c.create_line(*pts, fill=TEXT, width=2, smooth=True)
            if line_label:
                c.create_text(pts[-2] - px(4), pts[-1] - px(6), text=line_label, fill=TEXT,
                              font=(FONT, 8), anchor="se")


def heatmap(c, tip, box, grid):
    x, y, w, h = box
    lw = px(34)
    cw = (w - lw) / 24
    ch = min(px(24), (h - px(22)) / 7)
    peak = max(max(r) for r in grid)
    for d in range(7):
        cy = y + d * ch
        c.create_text(x + lw - px(6), cy + ch / 2, text=WEEKDAYS[d], fill=MUTED, font=(FONT, 8), anchor="e")
        for hr in range(24):
            v = grid[d][hr]
            color = HEAT_ZERO if v == 0 else mix(HEAT_LOW, HEAT_HIGH, (v / peak) ** 0.8)
            x0 = x + lw + hr * cw
            tag = f"cell{d}_{hr}"
            c.create_rectangle(x0 + 1, cy + 1, x0 + cw - 1, cy + ch - 1, fill=color, outline="", tags=tag)
            text = f"{WEEKDAYS[d]} {hour_range(hr)}\n{plural(v, 'urge')}"
            c.tag_bind(tag, "<Enter>", lambda e, x0=x0, cy=cy, t=text: tip.show(x0 + cw / 2, cy, t))
            c.tag_bind(tag, "<Leave>", lambda e: tip.hide())
    by = y + 7 * ch + px(6)
    for hr in range(0, 24, 3):
        c.create_text(x + lw + (hr + 0.5) * cw, by, text=HOURS[hr], fill=MUTED, font=(FONT, 8), anchor="n")


def intensity_chart(c, tip, box, series):
    x, y, w, h = box
    pl, pr, pt, pb = x + px(30), x + w - px(8), y + px(6), y + h - px(18)
    for v, label in ((1, "1"), (3, "3"), (5, "5")):
        yy = pb - (v - 1) / 4 * (pb - pt)
        c.create_line(pl, yy, pr, yy, fill=GRID)
        c.create_text(pl - px(6), yy, text=label, fill=MUTED, font=(FONT, 8), anchor="e")
    n = len(series)
    step = (pr - pl) / max(n - 1, 1)
    r = px(4)
    for i, (day, v) in enumerate(series):
        if v is not None:
            cx, cy = pl + i * step, pb - (v - 1) / 4 * (pb - pt)
            c.create_oval(cx - r - px(6), cy - r - px(6), cx + r + px(6), cy + r + px(6),
                          fill=CHART_BG, outline="", tags=f"pt{i}")
    run = []
    points = []
    for i, (day, v) in enumerate(series):
        if v is None:
            if len(run) >= 4:
                c.create_line(*run, fill=ACCENT, width=2)
            run = []
            continue
        cx, cy = pl + i * step, pb - (v - 1) / 4 * (pb - pt)
        run += [cx, cy]
        points.append((cx, cy, day, v))
    if len(run) >= 4:
        c.create_line(*run, fill=ACCENT, width=2)
    for cx, cy, day, v in points:
        tag = f"pt{series.index((day, v))}"
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=ACCENT, outline=CHART_BG, width=2, tags=tag)
        c.tag_bind(tag, "<Enter>", lambda e, cx=cx, cy=cy, t=f"{day:%a %d %b}\naverage {v:.1f} / 5": tip.show(cx, cy - r, t))
        c.tag_bind(tag, "<Leave>", lambda e: tip.hide())
    for i in (0, n // 2, n - 1):
        c.create_text(pl + i * step, pb + px(4), text=f"{series[i][0]:%d %b}", fill=MUTED, font=(FONT, 8), anchor="n")
    if not points:
        c.create_text((pl + pr) / 2, (pt + pb) / 2, text="Rate urges when the lock ends and they show up here.",
                      fill=MUTED, font=(FONT, 10))


def hbars(c, box, rows, label_w=170, note_w=110):
    """rows: [(name, count, note, note_colour)] - one horizontal bar each, count after the bar, note at the right."""
    x, y, w, h = box
    peak = max((r[1] for r in rows), default=0) or 1
    lw, nw = px(label_w), px(note_w)
    rh = min(px(30), h / max(len(rows), 1))
    for i, (name, v, note, note_colour) in enumerate(rows):
        cy = y + i * rh + rh / 2
        c.create_text(x, cy, text=name, fill=TEXT, font=(FONT, 10), anchor="w")
        bar_w = (w - lw - nw - px(30)) * v / peak
        if v:
            c.create_rectangle(x + lw, cy - px(7), x + lw + bar_w, cy + px(7), fill=ACCENT_SOFT, outline="")
        c.create_text(x + lw + bar_w + px(8), cy, text=str(v), fill=TEXT, font=(FONT, 10), anchor="w")
        if note:
            c.create_text(x + w, cy, text=note, fill=note_colour, font=(FONT, 9), anchor="e")


def relief_note(relief, key):
    """'↓ 1.8 calmer' style note from start-vs-end ratings, or '' when never measured."""
    if key not in relief:
        return "", MUTED
    drop, n = relief[key]
    if drop > 0.05:
        return f"▼ {drop:.1f} calmer ({n})", GOOD
    if drop < -0.05:
        return f"▲ {-drop:.1f} stronger ({n})", WARN
    return f"no change ({n})", MUTED


def choice_rows(counts, relief):
    rows = []
    for k, v in counts.items():
        note, colour = relief_note(relief, k)
        rows.append((OPTION_NAMES.get(k, "Handled it on my own"), v, note, colour))
    return rows


def delta_line(now, before, unit):
    diff = now - before
    if diff < 0:
        return f"▼ {-diff} fewer than {unit}", GOOD
    if diff > 0:
        return f"▲ {diff} more than {unit}", WARN
    return f"same as {unit}", MUTED


class ProgressWindow:
    def __init__(self, root, log):
        self.log = log
        self.win = tk.Toplevel(root, bg=BG, padx=px(20), pady=px(16))
        self.win.title("Urge Button - Progress")
        self.win.resizable(False, False)
        self.render()

    def tile(self, parent, label, value, sub, sub_color=MUTED):
        f = tk.Frame(parent, bg=PANEL, padx=px(14), pady=px(8), width=px(206), height=px(104))
        f.pack(side="left", padx=(0, px(10)))
        f.pack_propagate(False)
        tk.Label(f, text=label, font=(FONT, 9), fg=MUTED, bg=PANEL, anchor="w").pack(fill="x")
        tk.Label(f, text=value, font=(FONT, 22, "bold"), fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
        tk.Label(f, text=sub, font=(FONT, 9), fg=sub_color, bg=PANEL, anchor="w").pack(fill="x")

    def review(self, r):
        """'Last week in review': a few plain sentences, only the ones there's data for."""
        if not r:
            return
        facts = []
        total, prev = r["total"], r["previous"]
        if total < prev:
            facts.append((f"{plural(total, 'urge')}, down from {prev} the week before", GOOD))
        elif total > prev:
            facts.append((f"{plural(total, 'urge')}, up from {prev} the week before", WARN))
        else:
            facts.append((f"{plural(total, 'urge')}, same as the week before", TEXT))
        if r["calm_days"] is not None:
            facts.append((f"{r['calm_days']} of 7 days were calmer than your usual", GOOD if r["calm_days"] >= 4 else TEXT))
        if r["hardest_hour"] is not None:
            facts.append((f"Hardest hour: {hour_range(r['hardest_hour'])}", TEXT))
        if total:
            facts.append((f"Quietest day: {FULL_DAYS[r['quietest_day']]}", TEXT))
        if r["top_trigger"]:
            facts.append((f"Most common trigger: {r['top_trigger']}", TEXT))
        if r["best_option"]:
            key, drop = r["best_option"]
            facts.append((f"What helped most: {OPTION_NAMES[key]} ({drop:.1f} calmer)", GOOD))
        panel = tk.Frame(self.win, bg=PANEL, padx=px(16), pady=px(10))
        panel.pack(fill="x", pady=(0, px(12)))
        tk.Label(panel, text="Last week in review", font=(FONT, 12, "bold"), fg=TEXT, bg=PANEL).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, px(4)))
        for i, (text, colour) in enumerate(facts[:6]):
            tk.Label(panel, text="• " + text, font=(FONT, 10), fg=colour, bg=PANEL, anchor="w").grid(
                row=1 + i // 3, column=i % 3, sticky="w", padx=(0, px(28)), pady=px(1))

    def canvas(self, parent, w, h):
        c = tk.Canvas(parent, width=w, height=h, bg=CHART_BG, highlightthickness=0)
        c.pack(pady=(0, px(10)), anchor="w")
        return c, Tip(c)

    def render(self):
        for child in self.win.winfo_children():
            child.destroy()
        log = self.log
        now = log.now()

        locks = sum(1 for e in log.events if e.get("kind", "lock") == "lock")
        head = tk.Frame(self.win, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Your progress", font=(FONT, 20, "bold"), fg=TEXT, bg=BG).pack(side="left")
        button(head, "Close", self.win.destroy).pack(side="right")
        tk.Label(self.win, text=f"{plural(len(log.events), 'urge')} logged in all ({locks} with the lock, "
                                f"{len(log.events) - locks} on your own). Fewer, weaker and further apart is the trend you're after.",
                 font=(FONT, 10), fg=MUTED, bg=BG, anchor="w").pack(fill="x", pady=(px(2), px(12)))

        tiles = tk.Frame(self.win, bg=BG)
        tiles.pack(fill="x", pady=(0, px(12)))
        today = log.today()
        self.tile(tiles, "Today", str(today), *delta_line(today, log.yesterday_by_now(), "yesterday by now"))
        week = log.this_week()
        self.tile(tiles, "This week", str(week), *delta_line(week, log.last_week_by_now(), "last week by now"))
        since = log.since_last()
        last = log.last_time()
        self.tile(tiles, "Since your last urge", format_gap(since) if since is not None else "-",
                  f"last one {last:%a %I:%M %p}".replace(" 0", " ") if last else "nothing logged yet")
        longest = log.longest_gap()
        on_it = longest is not None and since is not None and abs(longest - since) < 1
        self.tile(tiles, "Longest stretch", format_gap(longest) if longest is not None else "-",
                  "you're on it right now" if on_it else (f"current: {format_gap(since)}" if since else ""),
                  GOOD if on_it else MUTED)
        calm = log.calmer_days(30)
        if calm:
            run = calm["run"]
            self.tile(tiles, "Calmer days, last 30", f"{calm['calm']} of {calm['of']}",
                      f"{plural(run, 'day')} in a row now · best {calm['best_run']}" if run else
                      f"best run {plural(calm['best_run'], 'day')}", GOOD if run >= 2 else MUTED)
        else:
            self.tile(tiles, "Calmer days, last 30", "-", "days below your own average")

        self.review(log.week_review())

        cols = tk.Frame(self.win, bg=BG)
        cols.pack(fill="x")
        left = tk.Frame(cols, bg=BG)
        left.pack(side="left", anchor="n", padx=(0, px(10)))
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", anchor="n")
        LW, RW = px(600), px(460)

        # Today by hour
        c, tip = self.canvas(left, LW, px(176))
        hours = log.by_hour()
        titled(c, "Today, hour by hour", f"{plural(today, 'urge')} so far today")
        bar_chart(c, tip, (px(10), px(60), LW - px(26), px(106)), hours,
                  {i: HOURS[i] for i in range(0, 24, 3)},
                  [f"{hour_range(i)}\n{plural(v, 'urge')}" for i, v in enumerate(hours)],
                  highlight={now.hour})
        if today == 0:
            c.create_text(LW / 2, px(108), text="Nothing logged yet today.", fill=MUTED, font=(FONT, 10))

        # Last 30 days with a 7-day average
        c, tip = self.canvas(left, LW, px(200))
        days = log.per_day(30)
        counts = [v for _, v in days]
        extended = [v for _, v in log.per_day(36)]
        avg = [sum(extended[i:i + 7]) / 7 for i in range(30)]
        titled(c, "Last 30 days", f"{plural(sum(counts), 'urge')} · line is the 7-day average")
        bar_chart(c, tip, (px(10), px(60), LW - px(26), px(130)), counts,
                  {i: f"{days[i][0]:%d %b}" for i in (0, 7, 14, 21, 29)},
                  [f"{d:%a %d %b}\n{plural(v, 'urge')}\n7-day avg {a:.1f}" for (d, v), a in zip(days, avg)],
                  highlight={29}, line=avg)

        # Strength trend
        c, tip = self.canvas(left, LW, px(176))
        titled(c, "How strong the urges were", "average rating when they hit, per day · 1 = mild, 5 = intense")
        intensity_chart(c, tip, (px(10), px(58), LW - px(26), px(108)), log.intensity_per_day(30))

        # When urges hit
        c, tip = self.canvas(right, RW, px(214))
        titled(c, "When urges hit", "last 30 days by day and hour · brighter = more")
        heatmap(c, tip, (px(10), px(56), RW - px(24), px(150)), log.heat(30))

        # What you did, and whether it helped
        c, tip = self.canvas(right, RW, px(196))
        titled(c, "What you did instead", "last 30 days · right side: how much calmer at unlock than at the start")
        hbars(c, (px(16), px(58), RW - px(32), px(132)), choice_rows(log.choice_counts(30), log.relief_by_choice(30)),
              label_w=160, note_w=120)

        # What sets it off
        c, tip = self.canvas(right, RW, px(162))
        titled(c, "What sets it off", "last 30 days · tap these in when the lock ends")
        trig = log.trigger_counts(30)[:5]
        if trig:
            hbars(c, (px(16), px(58), RW - px(32), px(98)), [(n, v, "", MUTED) for n, v in trig[:4]], label_w=130, note_w=0)
        else:
            c.create_text(RW / 2, px(104), text="Nothing yet. Pick what set it off when a lock ends.",
                          fill=MUTED, font=(FONT, 10))

        self.win.after(60_000, self._refresh)

    def _refresh(self):
        if self.win.winfo_exists():
            self.render()


def fake_log(path, days=40, seed=7):
    """Synthetic history for previews: evening-heavy, slowly improving."""
    import random

    from urge_log import EventLog

    rng = random.Random(seed)
    log = EventLog(path)
    log.events = []
    end = log.now()
    for back in range(days, -1, -1):
        day = (end - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        n = max(0, int(rng.gauss(2 + back / 10, 1.2)))
        for _ in range(n):
            hour = min(23, max(0, int(rng.gauss(21, 3))))
            t = day + timedelta(hours=hour, minutes=rng.randrange(60))
            if t > end:
                continue
            kind = "logged" if rng.random() < 0.2 else "lock"
            choices = [] if kind == "logged" else rng.sample(["breathe", "walk", "spotify", "sudoku", "friend"], rng.choice([0, 1, 1, 2]))
            start = None if rng.random() < 0.2 else max(1, min(5, round(rng.gauss(2.5 + back / 20, 1))))
            help_ = {"walk": 2, "friend": 1.5, "breathe": 1.2, "spotify": 1, "sudoku": 0.5}
            drop = max([help_.get(ch, 0.3) for ch in choices] or [0.3]) + rng.gauss(0, 0.6)
            finish = None if start is None or kind == "logged" else max(1, min(5, round(start - drop)))
            triggers = rng.sample(["Bored", "Stressed", "Lonely", "Tired", "Late night", "After gaming"],
                                  rng.choice([0, 1, 1, 2]))
            log.events.append({"ts": t.isoformat(timespec="seconds"), "kind": kind, "minutes": 3,
                               "choices": choices, "intensity_start": start, "intensity": finish,
                               "triggers": triggers})
    log.save()
    return log
