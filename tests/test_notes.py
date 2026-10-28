import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import notes  # noqa: E402

FORMED = (
    "[2026-10-28 14:08:12] written: forming written-2026-10-28 from 4 capture(s), asking claude-opus-4-1\n"
    "[2026-10-28 14:08:21] written: wrote entries/2026/10/written-2026-10-28.md\n"
    "[2026-10-28 14:08:22] doc: Voice notes updated\n"
)
NOTHING = "[2026-10-28 14:08:21] form: nothing written on Wed Oct 28\n"
ALREADY = "[2026-10-28 14:08:21] form: Wed Oct 28 is already formed, nothing new\n"
BUSY = ("[2026-10-28 14:08:21] lock: another run is in progress (pid 1, started 2026-10-28 14:02:03); "
        "exiting without touching anything\n")
FAILED = "[2026-10-28 14:08:21] claude: exited 1: something went wrong in the model call\n"


def test_classify_formed_points_at_the_entry():
    r = notes.classify(0, 0, FORMED)
    assert r.kind == "formed" and r.line == "Your notes are formed"
    assert r.entry == notes.FOLDER / "entries/2026/10/written-2026-10-28.md"


def test_classify_nothing_new_today():
    r = notes.classify(0, 0, NOTHING)
    assert (r.kind, r.line, r.entry) == ("nothing", "Nothing new in your inbox today", None)


def test_classify_already_formed():
    r = notes.classify(0, 0, ALREADY)
    assert (r.kind, r.line) == ("already", "Already up to date, nothing new since last time")


def test_classify_busy_when_another_run_holds_the_lock():
    r = notes.classify(0, 2, BUSY)
    assert (r.kind, r.line) == ("busy", "Busy right now, try again in a minute")


def test_classify_failed_names_the_log_and_the_last_line():
    r = notes.classify(0, 1, FAILED)
    assert r.kind == "failed" and r.gist == "" and r.entry is None
    assert r.line.startswith("Could not form your notes, see pipeline\\logs")
    assert "something went wrong" in r.line
    assert notes.classify(2, 0, "").kind == "failed"          # a token problem in watch and nothing formed
    assert notes.classify(0, 0, "").kind == "failed"          # nothing recognisable at all
    assert notes.classify(0, 1, "a" * 200).line == "Could not form your notes, see pipeline\\logs"  # a long last line is left off


def test_gist_is_the_first_line_under_the_heading(tmp_path):
    entry = tmp_path / "written-2026-10-28.md"
    entry.write_text("---\nentry_id: written-2026-10-28\nkind: written\n---\n## Wed Oct 28 · written\n\n"
                     "**Five channels, one system.** Most of the day went on the marketing plan.\n\nMore here.\n",
                     encoding="utf-8")
    assert notes.gist(entry) == "Five channels, one system. Most of the day went on the marketing plan."
    assert notes.gist(tmp_path / "missing.md") == ""
    assert notes.gist(None) == ""


def test_doc_url_from_state_json(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    monkeypatch.setattr(notes, "PIPELINE", tmp_path)
    assert notes.doc_url() is None
    state.write_text(json.dumps({"google": {"running_doc_id": "abc123"}}), encoding="utf-8")
    assert notes.doc_url() == "https://docs.google.com/document/d/abc123/edit"
    state.write_text("not json", encoding="utf-8")
    assert notes.doc_url() is None


def test_form_now_runs_watch_then_form_and_reads_the_gist(tmp_path, monkeypatch):
    entry = tmp_path / "entries" / "2026" / "10" / "written-2026-10-28.md"
    entry.parent.mkdir(parents=True)
    entry.write_text("## Wed Oct 28 · written\n\nThe gist line.\n", encoding="utf-8")
    monkeypatch.setattr(notes, "FOLDER", tmp_path)
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd[-1], kw["cwd"], kw["creationflags"], kw["env"].get("PYTHONUTF8"), kw["timeout"]))
        return subprocess.CompletedProcess(cmd, 0, stdout=FORMED if cmd[-1] == "form" else "", stderr="")

    monkeypatch.setattr(notes.subprocess, "run", fake_run)
    r = notes.form_now(timeout=600)
    assert [c[0] for c in calls] == ["watch", "form"]
    assert all(c[1:] == (str(notes.PIPELINE), notes.NO_WINDOW, "1", 600) for c in calls)
    assert r.kind == "formed" and r.gist == "The gist line."


def test_form_now_never_raises(monkeypatch):
    def boom(cmd, **kw):
        raise OSError("no python here")

    monkeypatch.setattr(notes.subprocess, "run", boom)
    r = notes.form_now()
    assert r.kind == "failed" and r.line.startswith("Could not form your notes")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 600)

    monkeypatch.setattr(notes.subprocess, "run", slow)
    assert notes.form_now().kind == "failed"
