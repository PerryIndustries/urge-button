"""The Food timer: one press starts it, and when it runs out a big note says the order is here.

The end time is a wall-clock timestamp in the settings, so a restart (an update, a reboot) picks it back up.
"""

DEFAULT_MINUTES = 25
EXTRA_MINUTES = (5, 15, 30, 60)
SCROLL_MINUTES = 5  # one wheel notch over the Food button


def left(until, now):
    """Seconds until the order is due, 0 once it is; None when no timer is running."""
    if until is None:
        return None
    return max(0, int(until - now))


def extend(until, now, minutes):
    """Add minutes to a running timer, or start them from now when it has already run out (or never ran).

    Negative minutes take time off, but never past 1 minute left.
    """
    return max(max(until or now, now) + minutes * 60, now + 60)


def amount(minutes):
    """An add-time button: '+5 min', '+1 hr'."""
    if minutes % 60 == 0:
        return f"+{minutes // 60} hr"
    return f"+{minutes} min"


def label(seconds):
    """The line under the Food button."""
    if seconds is None:
        return f"{DEFAULT_MINUTES}m"
    if seconds <= 0:
        return "here!"
    minutes = max(1, (seconds + 59) // 60)
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m left" if minutes % 60 else f"{minutes // 60}h left"
    return f"{minutes}m left"
