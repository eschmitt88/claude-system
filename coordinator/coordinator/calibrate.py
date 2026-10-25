"""Auto-calibrate the plan ceilings from observed utilisation.

Every logged reading (ratelimits.LOG_FILE) is one equation:

    L_i = cost(window_start .. observed_at) / (used_pct / 100)

with cost priced by transcripts.py, so L is in the same units as the
deltas ccusage.py adds on top of an anchor. Per window, L = median of
its L_i; readings below MIN_PCT are dropped (a coarse/rounded % early
in a window makes L_i noisy).

Bonus weeks and quota-weighting changes are absorbed per window rather
than modelled. That's fine: L only scales the *delta since the last
reading*, so its error is second-order whenever an anchor exists.
`cache_read_share` is recorded per window so the "quota weights cache
reads differently than list price" hypothesis can be checked by eye
once there are windows with different mixes — deliberately no
multi-parameter fit until then.

State: ~/.claude/state/quota-calibration.json (private, never in git).
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import ratelimits, transcripts

CAL_FILE = ratelimits.STATE_DIR / "quota-calibration.json"
MIN_PCT = 20.0
# Readings older than this are ignored (bounds the transcript scan).
MAX_AGE = timedelta(weeks=8)
# poller.py calls maybe_run() every 30s; recalibrate at most this often.
MIN_INTERVAL_S = 900
# resets_at may wobble by seconds between readings of one window.
_GROUP_S = 600
# How many past windows to keep, and to pool when the current one is thin.
_KEEP = {"five_hour": 60, "seven_day": 12}
_POOL = {"five_hour": 10, "seven_day": 3}
_MIN_N_CURRENT = 3


def load() -> dict:
    try:
        cal = json.loads(CAL_FILE.read_text())
    except (OSError, ValueError):
        cal = {}
    for w in ratelimits.WINDOWS:
        cal.setdefault(w, {})
    return cal


def _save(cal: dict) -> None:
    tmp = CAL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cal, indent=1, sort_keys=True))
    tmp.chmod(0o600)
    tmp.replace(CAL_FILE)


def _groups(now: float) -> dict:
    """{window: {group_key: [reading, ...]}} for recent readings."""
    out = {w: {} for w in ratelimits.WINDOWS}
    cutoff = now - MAX_AGE.total_seconds()
    for rec in ratelimits.observations():
        if rec["observed_at"] < cutoff:
            continue
        key = str(int(round(rec["resets_at"] / _GROUP_S) * _GROUP_S))
        out[rec["window"]].setdefault(key, []).append(rec)
    return out


def run(force: bool = False) -> dict:
    now = time.time()
    cal = load()
    groups = _groups(now)

    # Windows whose reading set changed since they were last fitted.
    todo = []
    for w, by_key in groups.items():
        period = ratelimits.WINDOWS[w].total_seconds()
        for key, recs in by_key.items():
            prev = cal[w].get(key)
            if not force and prev and prev.get("n_readings") == len(recs):
                continue
            start = min(r["resets_at"] for r in recs) - period
            todo.append((w, key, recs, start))

    if todo:
        lo = min(t[3] for t in todo)
        hi = max(r["observed_at"] for t in todo for r in t[2])
        _, records = transcripts.scan(
            datetime.fromtimestamp(lo, timezone.utc),
            datetime.fromtimestamp(hi + 60, timezone.utc),
        )
        cum = transcripts.CumulativeCost(records)
        for w, key, recs, start in todo:
            c0, t0, r0 = cum.at(start)
            ls = []
            for r in recs:
                if r["used_pct"] < MIN_PCT:
                    continue
                c1, _, _ = cum.at(r["observed_at"])
                if c1 > c0:
                    ls.append((c1 - c0) / (r["used_pct"] / 100.0))
            last = max(recs, key=lambda r: r["observed_at"])
            c1, t1, r1 = cum.at(last["observed_at"])
            cal[w][key] = {
                "resets_at": last["resets_at"],
                "limit_usd": statistics.median(ls) if ls else None,
                "n": len(ls),
                "n_readings": len(recs),
                "last_pct": last["used_pct"],
                "cost_usd": round(c1 - c0, 2),
                "tokens": int(t1 - t0),
                "cache_read_share": round((r1 - r0) / (t1 - t0), 4) if t1 > t0 else None,
            }

    for w, keep in _KEEP.items():
        for key in sorted(cal[w], key=int)[:-keep]:
            del cal[w][key]
    cal["computed_at"] = now
    _save(cal)
    return cal


def maybe_run() -> None:
    """Cheap poller hook: refit only when new readings were logged."""
    try:
        log_mtime = ratelimits.LOG_FILE.stat().st_mtime
    except OSError:
        return
    last = load().get("computed_at") or 0
    if log_mtime > last and time.time() - last >= MIN_INTERVAL_S:
        run()


def current_limit(window: str, cal: Optional[dict] = None) -> tuple[Optional[float], str]:
    """(ceiling, source) for the window in force now. Source is
    'window' (this window's own fit, n >= 3), 'pooled' (median of recent
    past windows), 'window-thin' (this window, n < 3, nothing to pool), or
    'none'."""
    cal = cal if cal is not None else load()
    fits = cal.get(window) or {}
    cur = ratelimits.current_window(window)
    cur_key = None
    if cur is not None:
        cur_key = str(int(round(cur[1].timestamp() / _GROUP_S) * _GROUP_S))
    mine = fits.get(cur_key) if cur_key else None
    if mine and mine.get("limit_usd") and mine["n"] >= _MIN_N_CURRENT:
        return mine["limit_usd"], "window"
    past = [
        f["limit_usd"] for k, f in sorted(fits.items(), key=lambda kv: int(kv[0]))
        if k != cur_key and f.get("limit_usd")
    ][-_POOL[window]:]
    if past:
        return statistics.median(past), "pooled"
    if mine and mine.get("limit_usd"):
        return mine["limit_usd"], "window-thin"
    return None, "none"


def main() -> int:
    ap = argparse.ArgumentParser(description="Refit plan-quota ceilings from observed utilisation.")
    ap.add_argument("--force", action="store_true", help="refit every window, not just changed ones")
    args = ap.parse_args()
    cal = run(force=args.force)
    for w in ratelimits.WINDOWS:
        lim, src = current_limit(w, cal)
        print(f"{w}: ceiling {'n/a' if lim is None else f'${lim:,.2f}'} ({src})")
        for key in sorted(cal[w], key=int)[-8:]:
            f = cal[w][key]
            when = datetime.fromtimestamp(f["resets_at"]).strftime("%a %m-%d %H:%M")
            lim_s = "-" if f["limit_usd"] is None else f"${f['limit_usd']:,.2f}"
            print(f"  resets {when}  L={lim_s:>10}  n={f['n']:<3} last={f['last_pct']:.0f}%  "
                  f"${f['cost_usd']:,.2f}  cache_read={f['cache_read_share']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
