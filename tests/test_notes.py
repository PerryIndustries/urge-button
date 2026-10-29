import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import notes  # noqa: E402

PRE = "[2026-10-28 14:08:12] pull: 2 new note(s)\n[2026-10-28 14:08:40] doc: Voice notes updated\n"
NEWEST = "now: newest entries/2026/10/2026-10-28-today-slug.md\n"
BOTH = PRE + "now: 2 voice, 1 written\n" + NEWEST
ONE_VOICE = PRE + "now: 1 voice, 0 written\n" + NEWEST
WRITTEN_ONLY = PRE + "now: 0 voice, 3 written\n" + NEWEST
NOT_FETCHED = PRE + "now: 0 voice, 1 written\nnow: voice notes not fetched\n" + NEWEST
NOTHING = "[2026-10-28 14:08:21] now: nothing to do\nnow: 0 voice, 0 written\n"
NOTHING_NOT_FETCHED = "now: 0 voice, 0 written\nnow: voice notes not fetched\n"
BUSY = ("[2026-10-28 14:08:21] lock: another run is in progress (pid 1, started 2026-10-28 14:02:03); "
        "exiting without touching anything\n")
FAILED = "[2026-10-28 14:08:21] claude: exited 1: something went wrong in the model call\n"
NEWEST_PATH = notes.FOLDER / "entries/2026/10/2026-10-28-today-slug.md"
LOGS = "Could not form your notes, see pipeline\\logs"


def test_classify_formed_both_kinds_points_at_the_newest_entry():
    r = notes.classify(0, BOTH)
    assert r.kind == "formed" and r.line == "Added 2 voice notes and 1 written entry"
    assert r.entry == NEWEST_PATH


def test_classify_formed_singular_plural_and_zero_parts_omitted():
    assert notes.classify(0, ONE_VOICE).line == "Added 1 voice note"
    assert notes.classify(0, WRITTEN_ONLY).line == "Added 3 written entries"


def test_classify_formed_says_when_voice_notes_were_not_fetched():
    r = notes.classify(0, NOT_FETCHED)
    assert r.kind == "formed"
    assert r.line == "Added 1 written entry, voice notes could not be fetched"


def test_classify_nothing_new():
    r = notes.classify(0, NOTHING)
    assert (r.kind, r.line, r.entry) == ("nothing", "Nothing new since last time", None)


def test_classify_nothing_written_and_pull_failed():
    r = notes.classify(0, NOTHING_NOT_FETCHED)
    assert (r.kind, r.line) == ("nothing", "Nothing new in your inbox, and voice notes could not be fetched")


def test_classify_busy_when_another_run_holds_the_lock():
    r = notes.classify(2, BUSY)
    assert (r.kind, r.line) == ("busy", "Busy right now, try again in a minute")


def test_classify_failed_names_the_log_and_the_last_line():
    r = notes.classify(1, FAILED)
    assert r.kind == "failed" and r.gist == "" and r.entry is None
    assert r.line.startswith(LOGS)
    assert "something went wrong" in r.line
    assert notes.classify(2, "").kind == "failed"             # a token problem, no now: lines
    assert notes.classify(0, "").kind == "failed"             # nothing recognisable at all
    assert notes.classify(1, BOTH).kind == "failed"           # a nonzero exit is a failure even with now: lines
    assert notes.classify(1, "a" * 200).line == LOGS          # a long last line is left off


def test_gist_is_the_first_line_under_the_heading(tmp_path):
    entry = tmp_path / "2026-10-28-today-slug.md"
    entry.write_text("---\nentry_id: x\n---\n## Wed Oct 28 · 3:37pm\n\n"
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


def test_form_now_runs_only_now_and_reads_the_gist(tmp_path, monkeypatch):
    entry = tmp_path / "entries" / "2026" / "10" / "2026-10-28-today-slug.md"
    entry.parent.mkdir(parents=True)
    entry.write_text("## Wed Oct 28 · 3:37pm\n\nThe gist line.\n", encoding="utf-8")
    monkeypatch.setattr(notes, "FOLDER", tmp_path)
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd[1:], kw["cwd"], kw["creationflags"], kw["env"].get("PYTHONUTF8"), kw["timeout"]))
        return subprocess.CompletedProcess(cmd, 0, stdout=BOTH, stderr="")

    monkeypatch.setattr(notes.subprocess, "run", fake_run)
    r = notes.form_now()
    assert calls == [(["-m", "voicenotes_pipeline.cli", "now"], str(notes.PIPELINE), notes.NO_WINDOW, "1", 900)]
    assert r.kind == "formed" and r.gist == "The gist line."


def test_form_now_never_raises(monkeypatch):
    def boom(cmd, **kw):
        raise OSError("no python here")

    monkeypatch.setattr(notes.subprocess, "run", boom)
    r = notes.form_now()
    assert r.kind == "failed" and r.line.startswith("Could not form your notes")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 900)

    monkeypatch.setattr(notes.subprocess, "run", slow)
    assert notes.form_now().kind == "failed"
