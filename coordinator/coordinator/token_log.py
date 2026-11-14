"""Stop-hook sink: record one session's token spend as per-turn deltas.

Called by claude/hooks/token_logger.sh after every turn:

    python -m coordinator.token_log SESSION_ID TRANSCRIPT [PROJECT_ROOT]

A session's cumulative usage (transcripts.session_usage: deduped, subagents
included) is compared with what each sink already holds for that session, and
only the difference is appended. Summing a sink's rows therefore gives the
session total, and each sink stays consistent even if the other missed a
write. Two sinks:

  <project>/_meta/token_log.ndjson   read by scripts/chain_budget.py (/iterate
                                     ceilings); gitignored in projects
  ~/.claude/state.db token_events    read by /headroom --json and the dashboard

A delta is clamped at 0: a cumulative total below the recorded sum means the
transcript was rotated or the sink holds rows from the pre-dedup logger.
Under-counting is the safe direction for a spend ceiling's *history*, and the
warning on stderr makes it diagnosable.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .transcripts import session_usage

FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


def _delta(cum: dict, prev: dict, sink: str, sid: str) -> dict:
    out = {}
    clamped = []
    for f in FIELDS:
        d = int(cum.get(f, 0)) - int(prev.get(f, 0))
        if d < 0:
            clamped.append(f)
            d = 0
        out[f] = d
    if clamped:
        print(f"WARN token_log[{sink}]: delta clamped to 0 for {clamped} in session {sid}",
              file=sys.stderr)
    return out


def _ndjson_prev(path: Path, sid: str) -> dict:
    prev = dict.fromkeys(FIELDS, 0)
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return prev
    for ln in lines:
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if row.get("session_id") == sid:
            for f in FIELDS:
                prev[f] += int(row.get(f, 0) or 0)
    return prev


def record(session_id: str, transcript: str, project_root: str | None = None,
           db: bool = True) -> dict:
    """Append this turn's delta to both sinks; return the cumulative totals."""
    sid = session_id or "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    usage, tools = session_usage(Path(transcript))
    cum = {f: getattr(usage, f) for f in FIELDS}

    if project_root:
        ndjson = Path(project_root) / "_meta" / "token_log.ndjson"
        if ndjson.parent.is_dir():
            d = _delta(cum, _ndjson_prev(ndjson, sid), "ndjson", sid)
            row = {"timestamp": ts, "session_id": sid, **d, "tools_used_summary": tools}
            with ndjson.open("a") as fh:
                fh.write(json.dumps(row) + "\n")

    if db:
        from .db import connect
        from .writers import insert_token_event
        with connect() as c:
            got = c.execute(
                "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
                "       COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_creation_tokens),0)"
                "  FROM token_events WHERE session_id = ?", (sid,)).fetchone()
        prev = dict(zip(FIELDS, (int(v or 0) for v in got)))
        d = _delta(cum, prev, "state.db", sid)
        insert_token_event(session_id=sid,
                           project=Path(project_root).name if project_root else None,
                           **d, tools_used=tools, timestamp=ts)
    return cum


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    record(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
