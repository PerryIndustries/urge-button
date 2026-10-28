"""The Notes button: forms today's written notes right now through the voicenotes pipeline (~/Desktop/voicenotes).

The pipeline lives in its own repo with its own venv; this only runs its CLI (`watch` to pull the inbox, then
`form` for today) with no console window, reads the log lines back and turns them into one human line. Nothing
here imports tkinter, and nothing here reads the pipeline's secrets.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

FOLDER = Path.home() / "Desktop" / "voicenotes"
PIPELINE = FOLDER / "pipeline"
PYTHON = PIPELINE / "venv" / "Scripts" / "python.exe"
NO_WINDOW = 0x08000000

LINES = {
    "formed": "Your notes are formed",
    "nothing": "Nothing new in your inbox today",
    "already": "Already up to date, nothing new since last time",
    "busy": "Busy right now, try again in a minute",
    "failed": "Could not form your notes, see pipeline\\logs",
}
WROTE = re.compile(r"written: wrote (entries/\S+)")
SHORT = 80  # a last log line longer than this is left off the failure line


@dataclass
class Result:
    kind: str           # formed | nothing | already | busy | failed
    line: str           # one human line for the note beside the button
    gist: str = ""      # the first line of the entry, when formed
    entry: Path = None  # the entry file, when formed


def installed():
    return PYTHON.exists()


def _run(command, timeout):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([str(PYTHON), "-m", "voicenotes_pipeline.cli", command], cwd=str(PIPELINE),
                          creationflags=NO_WINDOW, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=timeout)


def form_now(timeout=600):
    """`watch` (pull the inbox) then `form` (today's entry). Never raises: a missing venv, a hang or anything unexpected is a failed Result.

    `form` first waits up to six minutes for a watch tick when one holds the lock, so the timeout stays long.
    """
    try:
        watch = _run("watch", timeout)
        form = _run("form", timeout)
    except Exception as e:  # noqa: BLE001 - this must never raise into the worker thread
        return Result("failed", f"{LINES['failed']}: {type(e).__name__}")
    result = classify(watch.returncode, form.returncode, (form.stdout or "") + (form.stderr or ""))
    if result.kind == "formed":
        result.gist = gist(result.entry)
    return result


def classify(watch_rc, form_rc, form_output):
    """The log lines of `form` (and the exit codes) -> what to tell you. Pure, so it is tested on real log lines."""
    out = form_output or ""
    if "another run is in progress" in out:
        return Result("busy", LINES["busy"])
    if "nothing written on" in out:
        return Result("nothing", LINES["nothing"])
    if "is already formed, nothing new" in out:
        return Result("already", LINES["already"])
    wrote = WROTE.search(out)
    if wrote and form_rc == 0:
        return Result("formed", LINES["formed"], entry=FOLDER / wrote.group(1))
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    last = re.sub(r"^\[[^\]]*\]\s*", "", lines[-1]) if lines else ""
    tail = f": {last}" if last and len(last) <= SHORT else ""
    return Result("failed", LINES["failed"] + tail)


def gist(entry_path):
    """The first non-empty line after the entry's `## ` heading, without markdown emphasis; "" when unreadable."""
    if not entry_path:
        return ""
    try:
        text = Path(entry_path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""
    seen_heading = False
    for line in text.splitlines():
        if not seen_heading:
            seen_heading = line.startswith("## ")
            continue
        line = line.strip()
        if line:
            return re.sub(r"[*_]{1,2}", "", re.sub(r"^[-*]\s+", "", line)).strip()
    return ""


def doc_url():
    """The running Google Doc the digest publishes to, from the pipeline's state.json (read only), or None."""
    try:
        state = json.loads((PIPELINE / "state.json").read_text(encoding="utf-8"))
        doc_id = state["google"]["running_doc_id"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else None
