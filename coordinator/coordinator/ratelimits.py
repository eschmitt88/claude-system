"""Ground-truth plan usage, as captured by claude/hooks/statusline.sh.

Claude Code hands its status line Anthropic's own utilisation for the
5-hour and 7-day windows (Pro/Max only, interactive sessions only). The
hook keeps the newest reading per window in STATE_FILE and appends every
change to LOG_FILE. Each record:

    {"used_pct": 41.0, "resets_at": <epoch s>, "observed_at": <epoch s>,
     "session_id": "..."}

`observed_at` is the mtime of the reporting session's transcript, i.e.
roughly when that session last got an API response — not when the status
line re-rendered, so a stale idle session can never overwrite a newer
reading from a busy one.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

STATE_DIR = Path(os.environ.get("CLAUDE_STATE_DIR") or Path.home() / ".claude" / "state")
STATE_FILE = STATE_DIR / "rate-limits.json"
LOG_FILE = STATE_DIR / "rate-limits.ndjson"

WINDOWS = {"five_hour": timedelta(hours=5), "seven_day": timedelta(days=7)}


def _valid(rec) -> bool:
    return (
        isinstance(rec, dict)
        and isinstance(rec.get("used_pct"), (int, float))
        and isinstance(rec.get("resets_at"), (int, float))
        and isinstance(rec.get("observed_at"), (int, float))
    )


def latest(window: str) -> Optional[dict]:
    """Newest stored reading for `five_hour` / `seven_day`, or None."""
    try:
        rec = json.loads(STATE_FILE.read_text()).get(window)
    except (OSError, ValueError, AttributeError):
        return None
    return rec if _valid(rec) else None


def observations() -> Iterator[dict]:
    """Every logged reading (each has a `window` key), oldest first."""
    try:
        fh = LOG_FILE.open()
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if _valid(rec) and rec.get("window") in WINDOWS:
                yield rec


def current_window(window: str, now: Optional[datetime] = None):
    """(start, end, anchor) for the window containing `now`, from the last
    known resets_at — rolled forward by whole periods if that reset has
    already passed (no session has reported since). anchor is the stored
    reading when it belongs to this window, else None. Returns None when
    no reading was ever stored. The 5h window only exists while a session
    is active, so it is never rolled forward."""
    rec = latest(window)
    if rec is None:
        return None
    now = now or datetime.now(timezone.utc)
    period = WINDOWS[window]
    end = datetime.fromtimestamp(rec["resets_at"], timezone.utc)
    if end <= now:
        if window == "five_hour":
            return None
        while end <= now:
            end += period
    start = end - period
    anchor = rec if rec["resets_at"] == end.timestamp() else None
    return start, end, anchor
