"""Keep one urge history across the PC and the phone, in a private GitHub repo.

Both apps read and write one file, `events.json`, in the repo named in Settings (default
PerryIndustries/urge-data). Every event has an `id` and an `u` (last-updated, epoch ms); merging takes
the union by id and, for the same id, the copy updated last. Merging is safe to repeat, so a sync
that loses a race just runs again.

Shared format, one event:
    {"id", "t" (epoch ms), "kind", "minutes", "choices", "intensity_start", "intensity", "triggers", "u"}
"""

import base64
import json
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_REPO = "PerryIndustries/urge-data"
PATH = "events.json"
FIELDS = ("kind", "minutes", "choices", "intensity_start", "intensity", "triggers")


def to_shared(event):
    """PC event (local ISO `ts`) -> shared format (epoch ms `t`)."""
    out = {"id": event["id"], "t": int(datetime.fromisoformat(event["ts"]).timestamp() * 1000), "u": event.get("u", 0)}
    for f in FIELDS:
        out[f] = event.get(f)
    return out


def from_shared(event):
    out = {"ts": datetime.fromtimestamp(event["t"] / 1000).isoformat(timespec="seconds"),
           "id": event["id"], "u": event.get("u", 0)}
    for f in FIELDS:
        out[f] = event.get(f)
    out["choices"] = out["choices"] or []
    out["triggers"] = out["triggers"] or []
    return out


def merge(*lists):
    """Union by id; for the same id keep the copy with the latest `u` (earlier list wins ties)."""
    best = {}
    for events in lists:
        for e in events:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            cur = best.get(e["id"])
            if cur is None or e.get("u", 0) > cur.get("u", 0):
                best[e["id"]] = e
    return sorted(best.values(), key=lambda e: e.get("t", 0))


def gh_cli_token():
    """This computer's GitHub CLI login, if there is one - so a PC needs no token typed in."""
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10,
                             creationflags=0x08000000)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class SyncError(Exception):
    pass


class GitHubFile:
    def __init__(self, repo, token, path=PATH):
        self.url = f"https://api.github.com/repos/{repo}/contents/{path}"
        self.token = token
        self.ctx = ssl.create_default_context()  # Windows' own certificate store

    def _call(self, method, body=None):
        req = urllib.request.Request(self.url, method=method, data=json.dumps(body).encode() if body else None)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "urge-button")
        try:
            with urllib.request.urlopen(req, timeout=20, context=self.ctx) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise SyncError(f"can't reach GitHub ({e})") from e

    def read(self):
        """(events, sha); ([], None) when the file doesn't exist yet."""
        status, body = self._call("GET")
        if status == 404:
            return [], None
        if status in (401, 403):
            raise SyncError("GitHub refused the token (check it has access to the data repo)")
        if status != 200:
            raise SyncError(f"GitHub said {status}")
        data = json.loads(base64.b64decode(body.get("content", "")).decode("utf-8") or "{}")
        return data.get("events", []), body.get("sha")

    def write(self, events, sha):
        payload = json.dumps({"version": 1, "events": events}, separators=(",", ":")).encode("utf-8")
        body = {"message": "sync", "content": base64.b64encode(payload).decode()}
        if sha:
            body["sha"] = sha
        status, _ = self._call("PUT", body)
        if status in (409, 422):
            return False  # someone else wrote first: read again and retry
        if status not in (200, 201):
            raise SyncError(f"GitHub said {status} when saving")
        return True


def sync(local_shared, remote_file, attempts=3):
    """Merge local events with the repo's copy and write back if anything changed. Returns the merged list."""
    for _ in range(attempts):
        remote, sha = remote_file.read()
        merged = merge(remote, local_shared)
        if merged == merge(remote):
            return merged
        if remote_file.write(merged, sha):
            return merged
    raise SyncError("the data file kept changing; will try again later")
