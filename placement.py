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


def geometry(x, y, w=None, h=None):
    """A Tk geometry string for a window at (x, y). Always "+x+y": Tk reads "-633" as an offset from the
    right/bottom edge, which throws windows on monitors left of or above the main one to the wrong side."""
    size = f"{w}x{h}" if w is not None else ""
    return f"{size}+{x}+{y}"


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


def clamp(monitors, x, y, w, h):
    """Slide a w x h window fully onto the monitor its centre is on, so no edge of it hangs off-screen."""
    cx, cy = x + w // 2, y + h // 2
    for m in monitors:
        if m.contains(cx, cy):
            return max(m.x, min(x, m.x + m.w - w)), max(m.y, min(y, m.y + m.h - h))
    return x, y


def named(monitors, name):
    """The monitor with exactly this device name, or None when it isn't connected."""
    return next((m for m in monitors if m.name == name), None)


def under(monitors, x, y, w, h):
    """The monitor a w x h window at (x, y) has its centre on, or None."""
    cx, cy = x + w // 2, y + h // 2
    return next((m for m in monitors if m.contains(cx, cy)), None)


def fit(monitor, x, y, w, h):
    """Slide a w x h window fully inside this monitor."""
    return max(monitor.x, min(x, monitor.x + monitor.w - w)), max(monitor.y, min(y, monitor.y + monitor.h - h))


def corner_spot(monitor, x, y, w, h, cw, ch):
    """Where a cw x ch window goes so it shares the corner of the w x h window at (x, y) that's nearest the edges
    of its monitor: the dot sits on the strip's outer corner, and the strip grows inward from the dot. Run it
    either way round (strip -> dot, dot -> strip) and the shared corner stays put."""
    right = x + w // 2 > monitor.x + monitor.w // 2
    bottom = y + h // 2 > monitor.y + monitor.h // 2
    return fit(monitor, x + w - cw if right else x, y + h - ch if bottom else y, cw, ch)


def centre_in(monitor, origin_x, origin_y):
    """Centre of the monitor, relative to a window whose top-left is (origin_x, origin_y)."""
    return monitor.x - origin_x + monitor.w // 2, monitor.y - origin_y + monitor.h // 2
