"""The Notes button: adds your new voice notes and written sessions right now through the voicenotes pipeline (~/Desktop/voicenotes).

The pipeline lives in its own repo with its own venv; this only runs its `now` command (one press: the inbox is
captured, voice notes are pulled, and every new voice note and writing session becomes an entry, in time order) with
no console window, reads the `now:` summary lines back and turns them into one human line. Nothing here imports
tkinter, and nothing here reads the pipeline's secrets.
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
    "nothing": "Nothing new since last time",
    "busy": "Busy right now, try again in a minute",
    "failed": "Could not form your notes, see pipeline\logs",
}
NOT_FETCHED = "voice notes could not be fetched"
COUNTS = re.compile(r"^now: (\d+) voice, (\d+) written\s*$", re.M)
NEWEST = re.compile(r"^now: newest (\S+)\s*$", re.M)
SHORT = 80  # a last log line longer than this is left off the failure line


@dataclass
class Result:
    kind: str           # formed | nothing | busy | failed
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


def form_now(timeout=900):
    """`now`: capture the inbox, pull voice notes, form every new voice note and writing session. Never raises: a missing venv, a hang or anything unexpected is a failed Result.

    `now` first waits for a watch tick that holds the lock, then does a Claude call per entry, so the timeout stays long.
    """
    try:
        run = _run("now", timeout)
    except Exception as e:  # noqa: BLE001 - this must never raise into the worker thread
        return Result("failed", f"{LINES['failed']}: {type(e).__name__}")
    result = classify(run.returncode, (run.stdout or "") + (run.stderr or ""))
    if result.kind == "formed":
        result.gist = gist(result.entry)
    return result


def _plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def classify(rc, output):
    """The exit code and output of `now` -> what to tell you. Pure, so it is tested on real output."""
    out = output or ""
    if "another run is in progress" in out:
        return Result("busy", LINES["busy"])
    counts = COUNTS.findall(out)
    if rc == 0 and counts:
        voice, written = (int(n) for n in counts[-1])
        unfetched = "now: voice notes not fetched" in out
        if not voice and not written:
            if unfetched:
                return Result("nothing", f"Nothing new in your inbox, and {NOT_FETCHED}")
            return Result("nothing", LINES["nothing"])
        parts = [p for p in (_plural(voice, "voice note", "voice notes") if voice else "",
                             _plural(written, "written entry", "written entries") if written else "") if p]
        line = "Added " + " and ".join(parts) + (f", {NOT_FETCHED}" if unfetched else "")
        newest = NEWEST.search(out)
        return Result("formed", line, entry=FOLDER / newest.group(1) if newest else None)
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
