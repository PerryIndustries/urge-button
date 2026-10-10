"""Where the button and the lock-screen message go. Pure functions, so they test without a screen."""

from dataclasses import dataclass

ANCHORS = [
    ("top-left", "Top left"), ("top-center", "Top middle"), ("top-right", "Top right"),
    ("bottom-left", "Bottom left"), ("bottom-center", "Bottom middle"), ("bottom-right", "Bottom right"),
]


@dataclass(frozen=True)
class Monitor:
    name: str          # Windows device name, e.g. \\.\DISPLAY2 - stable across restarts
    x: int
    y: int
    w: int
    h: int
    work: tuple        # (x, y, w, h) without the taskbar
    primary: bool = False

    def contains(self, px, py):
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


def numbered(monitors):
    """Monitors left to right (then top to bottom), as Windows' Display settings numbers them visually."""
    return sorted(monitors, key=lambda m: (m.x, m.y))


def label(monitor, index):
    main = " (main)" if monitor.primary else ""
    return f"Monitor {index + 1}: {monitor.w}\u00d7{monitor.h}{main}"


def find(monitors, name):
    """The monitor with this device name, else the main one, else the first."""
    for m in monitors:
        if m.name == name:
            return m
    for m in monitors:
        if m.primary:
            return m
    return monitors[0] if monitors else None


def anchor_position(monitor, w, h, anchor, margin=24):
    """Top-left corner for a w x h window at `anchor` inside the monitor's work area."""
    x0, y0, ww, wh = monitor.work
    vert, horiz = anchor.split("-")
    x = {"left": x0 + margin, "center": x0 + (ww - w) // 2, "right": x0 + ww - w - margin}[horiz]
    y = {"top": y0 + margin, "bottom": y0 + wh - h - margin}[vert]
    return x, y


def on_screen(monitors, x, y, w, h):
    """True when the window's centre lands on some monitor (so it can't get lost off-screen)."""
    cx, cy = x + w // 2, y + h // 2
    return any(m.contains(cx, cy) for m in monitors)


def centre_in(monitor, origin_x, origin_y):
    """Centre of the monitor, relative to a window whose top-left is (origin_x, origin_y)."""
    return monitor.x - origin_x + monitor.w // 2, monitor.y - origin_y + monitor.h // 2
