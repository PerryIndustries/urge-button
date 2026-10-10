"""Colours, fonts and the shared flat-button helper."""

import tkinter as tk

BG = "#0E0F10"
PANEL = "#1A1C1E"
PANEL_HI = "#24272A"
CHART_BG = "#141618"
GRID = "#2A2D31"
TEXT = "#F7F7F7"
MUTED = "#9AA0A6"
ACCENT = "#6A75F7"
ACCENT_SOFT = "#454C9E"
GOOD = "#59DAC3"
WARN = "#E8B35A"
BAD = "#F2726F"
FONT = "Segoe UI"

# Sequential ramp for the heatmap: one hue, dark -> light on the dark surface.
HEAT_LOW = "#262A52"
HEAT_HIGH = "#C3C8FF"
HEAT_ZERO = "#1D1F22"

SCALE = 1.0  # set from the screen DPI at startup so pixel sizes track font sizes


def px(n):
    return int(round(n * SCALE))


def init_scale(root):
    global SCALE
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)


def mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def button(master, text, command, primary=False, size=12, bg=None):
    base = bg or (ACCENT if primary else PANEL_HI)
    b = tk.Label(
        master, text=text, font=(FONT, size, "bold" if primary else "normal"),
        fg=TEXT, bg=base, padx=16, pady=8, cursor="hand2",
    )
    b.bind("<Button-1>", lambda e: command())
    b.bind("<Enter>", lambda e: b.config(bg=mix(base, "#FFFFFF", 0.08)))
    b.bind("<Leave>", lambda e: b.config(bg=base))
    return b
