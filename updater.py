"""Keep the PC app up to date from GitHub, the way Rift Pen does with electron-updater.

Checks on start and every 6 hours. When origin/main has moved on, it fast-forwards the local
checkout in the background (only on `main`, only with no local edits, only a fast-forward), and the
new code runs the next time the app starts - or straight away from "Restart to update".
"""

import subprocess
from pathlib import Path

CHECK_SECONDS = 6 * 60 * 60
NO_WINDOW = 0x08000000


class Updater:
    def __init__(self, repo_dir, branch="main"):
        self.repo = Path(repo_dir)
        self.branch = branch
        self.ready = None    # "abc1234 Subject of the newest commit" once an update has been pulled
        self.status = "Not checked yet"

    def _git(self, *args, timeout=60):
        try:
            out = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True,
                                 timeout=timeout, creationflags=NO_WINDOW)
            return out.returncode, out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return 1, ""

    def check(self):
        """Fetch and fast-forward if there's something new. Returns the new `ready` text or None.

        Safe to call from a background thread; it only touches git and its own fields.
        """
        if not (self.repo / ".git").exists():
            self.status = "Not a git checkout, so it can't update itself"
            return None
        code, branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if code or branch != self.branch:
            self.status = f"On branch {branch or '?'}, not {self.branch}: updates are skipped"
            return None
        code, _ = self._git("fetch", "--quiet", "origin", self.branch)
        if code:
            self.status = "Couldn't reach GitHub; will try again later"
            return None
        _, local = self._git("rev-parse", "HEAD")
        _, remote = self._git("rev-parse", f"origin/{self.branch}")
        if local == remote:
            self.status = "Up to date"
            return self.ready
        if self._git("merge-base", "--is-ancestor", "HEAD", f"origin/{self.branch}")[0]:
            self.status = "This copy has its own commits; updates are skipped"
            return None
        if self._git("status", "--porcelain", "--untracked-files=no")[1]:
            self.status = "This copy has local edits; updates are skipped"
            return None
        if self._git("merge", "--ff-only", "--quiet", f"origin/{self.branch}")[0]:
            self.status = "The update couldn't be applied; will try again later"
            return None
        _, line = self._git("log", "-1", "--format=%h %s")
        self.ready = line or "new version"
        self.status = f"Update downloaded: {self.ready}"
        return self.ready
