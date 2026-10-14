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
    assert food.extend(None, 1000, food.DEFAULT_MINUTES) == 1000 + 25 * 60


def test_label_rounds_up_to_the_minute():
    assert food.label(None) == "25m"
    assert food.label(61) == "2m left"
    assert food.label(30) == "1m left"
    assert food.label(0) == "here!"
