"""Send the hard-hour heads-up to the phone as a push notification.

Runs every hour in GitHub Actions inside the private data repo (PerryIndustries/urge-data; workflow in
push/headsup.yml). Reads that repo's events.json (the synced history) and push.json (written by the phone
when you turn notifications on: the subscription, your time zone, your plan).

    python headsup_push.py <data-repo-dir> [--test]      VAPID_KEY_FILE=<pem> must be set
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LEAD_MINUTES = 20        # the job runs at about :40, so it looks at the hour that starts next
QUIET_AFTER_URGE = 30    # minutes: no heads-up right after you logged one
SUB = "https://perryindustries.github.io"  # contact for the push services; must be a bare origin or mailto:


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def hour_name(h):
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def risky_hours(events, now, days=28):
    """Same rule as the apps: at least 4 urges in that hour over 28 days, and twice the hourly average."""
    since = now - timedelta(days=days)
    counts = [0] * 24
    for e in events:
        if not isinstance(e.get("t"), (int, float)):
            continue
        t = datetime.fromtimestamp(e["t"] / 1000, now.tzinfo)
        if t >= since:
            counts[t.hour] += 1
    threshold = max(4, 2 * sum(counts) / 24)
    return {h for h, n in enumerate(counts) if n >= threshold}


def message(events, push, now):
    """(title, body) to send at `now` (an aware datetime in your time zone), or None."""
    if not push.get("enabled") or not push.get("subscription"):
        return None
    target = (now + timedelta(minutes=LEAD_MINUTES)).replace(minute=0, second=0, microsecond=0)
    if target.hour not in risky_hours(events, now):
        return None
    last = max((e["t"] for e in events if isinstance(e.get("t"), (int, float))), default=None)
    if last is not None and now.timestamp() * 1000 - last < QUIET_AFTER_URGE * 60_000:
        return None
    plan = (push.get("plan") or "").strip()
    body = f"{hour_name(target.hour)} is usually one of your harder hours. " + (
        f"Your plan: {plan}" if plan else "Have a plan ready: a walk, some music, or a text to someone.")
    return "Heads up", body


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0] if args else ".")
    push = load(root / "push.json")
    events = load(root / "events.json").get("events", [])
    now = datetime.now(ZoneInfo(push.get("tz") or "UTC"))
    if "--test" in sys.argv:
        msg = ("Urge Button", "Notifications work. You'll get a heads-up before your hard hours.") \
            if push.get("subscription") else None
    else:
        msg = message(events, push, now)
    if not msg:
        print("nothing to send")
        return

    from pywebpush import WebPushException, webpush

    try:
        webpush(push["subscription"], json.dumps({"title": msg[0], "body": msg[1]}),
                vapid_private_key=os.environ["VAPID_KEY_FILE"], vapid_claims={"sub": SUB}, ttl=1800)
        print("sent")
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            # the phone dropped this subscription (app removed, or notifications turned off): stop trying
            push["enabled"] = False
            push["expired"] = True
            (root / "push.json").write_text(json.dumps(push, indent=2), encoding="utf-8")
            print("subscription expired")
        else:
            print(f"push failed ({status})")
            sys.exit(1)


if __name__ == "__main__":
    main()
