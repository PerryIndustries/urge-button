import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import placement  # noqa: E402
from placement import Monitor  # noqa: E402
from urge_log import load_config, save_json  # noqa: E402

MAIN = Monitor(r"\\.\DISPLAY1", 0, 0, 2560, 1440, (0, 0, 2560, 1392), primary=True)
LEFT = Monitor(r"\\.\DISPLAY2", -1920, 200, 1920, 1080, (-1920, 200, 1920, 1040))


def test_numbered_left_to_right():
    assert placement.numbered([MAIN, LEFT]) == [LEFT, MAIN]
    assert placement.label(MAIN, 1) == "Monitor 2: 2560\u00d71440 (main)"


def test_find_falls_back_to_main_when_a_monitor_is_unplugged():
    assert placement.find([MAIN, LEFT], LEFT.name) == LEFT
    assert placement.find([MAIN, LEFT], r"\\.\DISPLAY9") == MAIN
    assert placement.find([MAIN, LEFT], None) == MAIN


def test_anchor_positions_use_the_work_area():
    assert placement.anchor_position(MAIN, 100, 50, "bottom-right", margin=10) == (2450, 1332)
    assert placement.anchor_position(MAIN, 100, 50, "top-center", margin=10) == (1230, 10)
    assert placement.anchor_position(LEFT, 100, 50, "top-left", margin=10) == (-1910, 210)


def test_on_screen_rejects_a_spot_on_an_unplugged_monitor():
    assert placement.on_screen([MAIN, LEFT], -1000, 500, 100, 50)
    assert not placement.on_screen([MAIN], -1000, 500, 100, 50)


def test_clamp_slides_an_overhanging_window_back_onto_its_monitor():
    assert placement.clamp([MAIN, LEFT], 2500, 1400, 100, 50) == (2460, 1390)
    assert placement.clamp([MAIN, LEFT], -1930, 190, 100, 50) == (-1920, 200)
    assert placement.clamp([MAIN, LEFT], 500, 300, 100, 50) == (500, 300)


def test_centre_in_is_relative_to_the_cover_window():
    # cover starts at the far-left monitor, so the main monitor's centre is offset by its width
    assert placement.centre_in(MAIN, -1920, 0) == (1920 + 1280, 720)


def test_geometry_keeps_negative_positions_from_the_left_and_top():
    assert placement.geometry(-633, -98) == "+-633+-98"
    assert placement.geometry(-1920, -1440, 3847, 2520) == "3847x2520+-1920+-1440"
    assert placement.geometry(40, 40, 100, 50) == "100x50+40+40"


def test_old_dragged_position_is_kept(tmp_path):
    path = tmp_path / "config.json"
    save_json(path, {"button_x": 500, "button_y": 300})
    assert load_config(path)["button_anchor"] == "custom"
    save_json(path, {})
    assert load_config(path)["button_anchor"] == "bottom-right"
