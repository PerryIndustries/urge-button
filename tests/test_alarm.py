import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import alarm  # noqa: E402

FRI = datetime(2026, 10, 23, 16, 10)


def test_label_says_off_with_no_alarm():
    assert alarm.label(None, FRI) == "off"


def test_label_drops_the_day_for_today():
    assert alarm.label("Fri Oct 23, 09:30 PM", FRI) == "9:30pm"


def test_label_names_the_day_for_later():
    assert alarm.label("Sat Oct 24, 11:00 AM", FRI) == "Sat 11am"
    assert alarm.label("Mon Oct 26, 12:00 PM", FRI) == "Mon 12pm"


def test_label_rolls_into_next_year():
    assert alarm.label("Fri Jan 1, 9:00 AM", datetime(2026, 12, 31, 23, 0)) == "Fri 9am"
