import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import food  # noqa: E402


def test_left_counts_down_and_stops_at_zero():
    assert food.left(None, 1000) is None
    assert food.left(1300, 1000) == 300
    assert food.left(900, 1000) == 0


def test_extend_adds_to_a_running_timer():
    assert food.extend(1300, 1000, 5) == 1600


def test_extend_starts_from_now_once_it_has_run_out():
    assert food.extend(900, 1000, 10) == 1600
    assert food.extend(None, 1000, food.DEFAULT_MINUTES) == 1000 + 5 * 60


def test_label_rounds_up_to_the_minute():
    assert food.label(None) == "5m"
    assert food.label(61) == "2m left"
    assert food.label(30) == "1m left"
    assert food.label(0) == "here!"


def test_label_shows_hours_for_long_timers():
    assert food.label(60 * 60) == "1h left"
    assert food.label(85 * 60) == "1h 25m left"


def test_taking_time_off_stops_at_one_minute():
    assert food.extend(1600, 1000, -5) == 1300
    assert food.extend(1100, 1000, -5) == 1060


def test_amount_names_hours():
    assert food.amount(5) == "+5 min"
    assert food.amount(60) == "+1 hr"
