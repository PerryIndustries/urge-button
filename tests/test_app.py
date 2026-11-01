"""The floating window itself: a real Tk App against settings and history in tmp_path, never %APPDATA%."""

import sys
import tkinter as tk
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import urge_button  # noqa: E402
from sudoku import SudokuLog  # noqa: E402
from placement import Monitor  # noqa: E402
from theme import px  # noqa: E402
from urge_log import EventLog, bored_name, load_config, load_json  # noqa: E402


class E:
    """A pointer event with only what the click-vs-drag handlers read."""

    def __init__(self, x, y):
        self.x_root, self.y_root = x, y


def labels(menu):
    return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(urge_button, "CONFIG_PATH", path)
    monkeypatch.setattr(urge_button, "load_config", lambda: load_config(path))
    return path


@pytest.fixture
def make_app(tmp_path, cfg_path):
    """A fresh App on the tmp settings (no hotkeys, no sync, no git), kept off the screen. Closed after the test."""
    apps = []

    def make():
        app = urge_button.App(log=EventLog(tmp_path / "events.json"), sudoku_log=SudokuLog(tmp_path / "sudoku.json"),
                              hotkey=False)
        app.root.withdraw()
        apps.append(app)
        return app

    yield make
    for app in apps:
        try:
            app.root.destroy()
        except tk.TclError:
            pass  # the test closed it itself


def test_minimize_is_a_dot_and_survives_a_restart(make_app, cfg_path):
    app = make_app()
    assert not app.minimized
    assert app.strip.winfo_manager() == "pack" and app.dot.winfo_manager() == ""
    full = app.width()
    app.minimize()
    assert app.minimized and load_json(cfg_path, {})["minimized"] is True
    assert app.dot.winfo_manager() == "pack" and app.strip.winfo_manager() == ""
    assert app.width() == app.height() == px(urge_button.App.DOT) < full
    assert "Restore" in labels(app.menu) and "Minimize" not in labels(app.menu)
    app.root.destroy()

    again = make_app()                       # a restart starts minimized
    assert again.minimized and again.dot.winfo_manager() == "pack" and again.strip.winfo_manager() == ""
    again.restore()
    assert not again.minimized and load_json(cfg_path, {})["minimized"] is False
    assert again.strip.winfo_manager() == "pack" and again.dot.winfo_manager() == ""
    assert again.width() == full
    assert "Minimize" in labels(again.menu) and "Restore" not in labels(again.menu)


MAIN = Monitor("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, (0, 0, 1920, 1040), primary=True)
LEFT = Monitor("\\\\.\\DISPLAY2", -1920, 0, 1920, 1080, (-1920, 0, 1920, 1040))


@pytest.fixture
def screens(monkeypatch):
    """The monitors the app sees; tests change the list to plug and unplug them."""
    mons = [MAIN, LEFT]
    monkeypatch.setattr(urge_button.winapi, "monitors", lambda: list(mons))
    return mons


def drop_at(app, x, y):
    """Drag the window so its top-left lands on (x, y), as a mouse drag would. (The test window is hidden, so Tk
    can't report where it is; the drop reads the position from here instead.)"""
    app._moved = True
    app.root.winfo_x, app.root.winfo_y = (lambda: x), (lambda: y)
    try:
        app._release(E(x, y), app.restore)
    finally:
        del app.root.winfo_x, app.root.winfo_y


def spot(app):
    w, h = app.width(), app.height()
    return (app.dot_spot if app.minimized else app.strip_spot)(urge_button.winapi.monitors(), w, h)


def test_dot_click_restores_but_a_drag_only_moves_it(make_app, cfg_path, screens):
    app = make_app()
    app.minimize()
    drop_at(app, -1800, 200)
    assert app.minimized                                   # a drag is not a click
    assert spot(app) == (-1800, 200, LEFT)                 # the dot stays where it was dropped
    assert load_json(cfg_path, {})["button_monitor"] == LEFT.name
    app._press(E(100, 100))
    app._release(E(101, 100), app.restore)
    assert not app.minimized


def test_dot_and_strip_share_one_spot_on_the_same_monitor(make_app, screens):
    app = make_app()
    drop_at(app, -700, 900)                                # strip near the bottom-right of the left monitor
    sx, sy, mon = spot(app)
    assert mon == LEFT and (sx, sy) == (-700, 900)
    sw, sh = app.width(), app.height()
    app.minimize()
    dx, dy, dmon = spot(app)
    d = app.width()
    assert dmon == LEFT and (dx + d, dy + d) == (sx + sw, sy + sh)   # the dot sits on the strip's outer corner
    drop_at(app, -1880, 20)                                # move the dot to the top-left of that monitor...
    app.restore()
    assert spot(app) == (-1880, 20, LEFT)                  # ...and the strip comes back growing out from it


def test_unplugged_monitor_falls_back_to_main_and_comes_back_when_plugged_in(make_app, cfg_path, screens):
    app = make_app()
    drop_at(app, -1500, 300)
    screens.remove(LEFT)
    assert spot(app) == (420, 300, MAIN)                   # same place on the main monitor while it's gone
    assert load_json(cfg_path, {})["button_monitor"] == LEFT.name   # but it still belongs to the left monitor
    screens.append(LEFT)
    assert spot(app) == (-1500, 300, LEFT)


def test_rearranging_monitors_keeps_it_on_its_own_monitor(make_app, screens):
    app = make_app()
    drop_at(app, -1500, 300)
    screens[1] = Monitor(LEFT.name, 1920, 0, 1920, 1080, (1920, 0, 1920, 1040))   # dragged to the right in Windows
    assert spot(app)[:2] == (2340, 300)


def test_a_spot_saved_as_desktop_coordinates_is_read_per_monitor(make_app, cfg_path, screens):
    cfg_path.write_text('{"button_x": -1260, "button_y": 40, "button_monitor": "\\\\\\\\.\\\\DISPLAY2", '
                        '"button_anchor": "custom"}')
    app = make_app()
    assert spot(app)[:2] == (-1260, 40)
    screens[1] = Monitor(LEFT.name, 1920, 0, 1920, 1080, (1920, 0, 1920, 1040))
    assert spot(app)[:2] == (2580, 40)


def test_a_monitor_change_moves_the_live_window(make_app, screens):
    app = make_app()
    drop_at(app, -1500, 300)
    screens.remove(LEFT)
    placed = []
    app.root.geometry = lambda g=None: placed.append(g)
    app._keep_on_top()
    assert placed and placed[-1].endswith("+420+300")
    placed.clear()
    app._keep_on_top()                                     # nothing changed since: left alone
    assert placed == []


class FakeBlocker:
    stopped = False

    def stop(self):
        self.stopped = True


def hold(widget, clock, seconds):
    """Press the hold control, let `seconds` go by on the injected clock, and tick it once."""
    widget.now = lambda: clock[0]
    widget.press()
    clock[0] += seconds
    widget.tick()


def test_hold_to_fire_needs_the_full_three_seconds(make_app):
    app = make_app()
    fired = []
    clock = [100.0]
    h = urge_button.HoldToFire(app.root, lambda: fired.append(1), now=lambda: clock[0])
    assert urge_button.HOLD_SECONDS == 3
    h.press()
    assert h.itemcget(h.label, "text") == "Hold... 3"
    clock[0] += 2.9
    h.tick()
    assert fired == [] and h.itemcget(h.label, "text") == "Hold... 1"
    h.release()                                            # let go early: nothing, and it resets
    assert fired == [] and h.itemcget(h.label, "text") == "Emergency exit"
    h.press()
    clock[0] += 1
    h.tick()
    assert fired == [] and h.itemcget(h.label, "text") == "Hold... 2"
    clock[0] += 2
    h.tick()
    assert fired == [1]                                    # three seconds: fires
    h.tick()
    h.release()
    h.press()
    clock[0] += 5
    h.tick()
    assert fired == [1]                                    # and only once


def test_emergency_exit_ends_the_lock_and_marks_the_urge(make_app, tmp_path):
    app = make_app()
    event = app.log.record_press(3)
    lock = app.lock = urge_button.LockScreen(app, 3, event, preview=True)
    lock.win.withdraw()
    lock.blocker = FakeBlocker()
    clock = [50.0]
    hold(lock.exit, clock, 1)
    assert lock.win.winfo_exists() and "emergency_exit" not in event
    clock[0] += 2
    lock.exit.tick()
    assert event["emergency_exit"] is True
    assert lock.blocker.stopped and not lock.win.winfo_exists() and app.lock is None
    assert load_json(tmp_path / "events.json", [])[0]["emergency_exit"] is True
    plain = app.log.record_press(3)                        # a lock that runs its course never carries the field
    lock2 = app.lock = urge_button.LockScreen(app, 3, plain, preview=True)
    lock2.win.withdraw()
    lock2.finish()
    assert not lock2.exit.winfo_exists()                   # once the timer is done, Unlock is the way out
    assert "emergency_exit" not in plain
    lock2.close()


def test_emergency_exit_closes_the_bored_panel_as_stopped(make_app):
    app = make_app()
    app.bored()
    panel = app.bored_panel
    panel.win.withdraw()
    panel.pick(bored_name("outside"))                      # the five-minute timer is running
    clock = [10.0]
    hold(panel.exit, clock, 3)
    assert not panel.win.winfo_exists()
    assert panel.event["done"] is False and panel.event["seconds"] == 0 and panel.event["choices"] == ["outside"]


def _settle(app, seconds=5):
    import time
    end = time.time() + seconds
    while app._notes_running and time.time() < end:
        app.root.update()
        time.sleep(0.05)


def test_a_crashing_notes_run_never_leaves_the_button_stuck(make_app, monkeypatch):
    import notes
    monkeypatch.setattr(notes, "installed", lambda: True)
    calls = []

    import threading
    gate = threading.Event()
    shown = []

    def boom(*a, **k):
        gate.wait(5)
        calls.append(1)
        raise ValueError("bad output")

    class FakeDone:
        def __init__(self, app, result):
            shown.append(result)
            self.win = tk.Toplevel(app.root)
            self.win.withdraw()

        def close(self):
            self.win.destroy()

    monkeypatch.setattr(notes, "form_now", boom)
    monkeypatch.setattr(urge_button, "NotesDone", FakeDone)
    app = make_app()
    app.notes_press()
    gate.set()
    assert app.notes_sub.cget("text") == "forming..."
    _settle(app)
    assert not app._notes_running and app.notes_sub.cget("text") == "form now"
    assert shown[0].kind == "failed" and "ValueError" in shown[0].line
    app.notes_press()
    _settle(app)
    assert len(calls) == 2 and not app._notes_running


def test_form_now_turns_any_exception_into_a_failed_result(monkeypatch):
    import notes

    def boom(command, timeout):
        raise ValueError("x")

    monkeypatch.setattr(notes, "_run", boom)
    result = notes.form_now()
    assert result.kind == "failed" and "ValueError" in result.line


def test_no_update_restart_while_notes_are_forming(make_app, monkeypatch):
    app = make_app()
    app.updater.ready = True
    monkeypatch.setattr(urge_button.winapi, "idle_seconds", lambda: 10_000)
    restarts = []
    monkeypatch.setattr(app, "restart_to_update", lambda: restarts.append(1))
    app._notes_running = True
    app._auto_restart()
    assert not restarts
    app._notes_running = False
    app._auto_restart()
    assert restarts == [1]


def test_screen_button_turns_the_monitors_off_after_a_beat(make_app, monkeypatch):
    app = make_app()
    calls = []
    monkeypatch.setattr(urge_button.winapi, "monitors_off", lambda: calls.append("off"))
    app.online = True  # previews (online False) never blank the real screens
    app.screen_press()
    assert calls == []  # not on the click itself, so the settling hand doesn't wake them
    app.root.after(1200, app.root.quit)
    app.root.mainloop()
    assert calls == ["off"]
    assert app.strip_size()[0] >= urge_button.px(app.W + app.BW + app.FW + app.SW)


def test_screen_button_does_nothing_in_a_preview(make_app, monkeypatch):
    app = make_app()
    calls = []
    monkeypatch.setattr(urge_button.winapi, "monitors_off", lambda: calls.append("off"))
    app.screen_press()
    app.root.after(1200, app.root.quit)
    app.root.mainloop()
    assert calls == []
