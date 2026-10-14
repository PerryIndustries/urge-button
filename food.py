"""The Food timer: one press starts it, and when it runs out a big note says the order is here.

The end time is a wall-clock timestamp in the settings, so a restart (an update, a reboot) picks it back up.
"""

DEFAULT_MINUTES = 25
EXTRA_MINUTES = (5, 10, 15)


def left(until, now):
    """Seconds until the order is due, 0 once it is; None when no timer is running."""
    if until is None:
        return None
    return max(0, int(until - now))


def extend(until, now, minutes):
    """Add minutes to a running timer, or start them from now when it has already run out (or never ran)."""
    return max(until or now, now) + minutes * 60


def label(seconds):
    """The line under the Food button."""
    if seconds is None:
        return f"{DEFAULT_MINUTES}m"
    if seconds <= 0:
        return "here!"
    return f"{max(1, (seconds + 59) // 60)}m left"
