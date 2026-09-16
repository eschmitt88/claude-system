"""Resource-aware agency verdict — how aggressively an autonomous loop
should spend *right now*.

Combines two signals:

1. **Reset-anchored token pacing.** The weekly quota resets, so unused
   tokens are wasted ("use it or lose it"). We compare tokens used so far
   against a steady spend that would consume the weekly limit exactly at
   reset. Being *behind* that pace (especially as the reset nears) means
   there is slack to spend more aggressively.
2. **Live hardware headroom.** CPU / RAM / GPU utilization and free disk
   from the latest poller sample. Below ~50% utilization there is room to
   run more work concurrently.

Returns a GO / SLOW / HOLD verdict plus the numbers behind it, so skills
in `agency: max` repos (and `/headroom`) can decide whether to proceed
without a human gate. Pure read path — no writes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import ccusage
from .readers import latest_hardware_sample

# A scheduled GPU job starting within this many minutes is "imminent": GPU
# work longer than that should wait or expect to share VRAM.
IMMINENT_MIN = 45.0

# A resource at/above this utilization is "busy" (user pref: be aggressive
# below ~50% utilization).
BUSY_PCT = 50.0
GPU_BUSY_PCT = 50.0
# Never run the tree dry — hold autonomous work if free disk drops below this.
MIN_DISK_FREE_GB = 25.0
# Weekly quota guardrail — hold once this fraction of the weekly budget is spent.
WEEKLY_HOLD_PCT = 90.0
# How far behind steady pace counts as "ample" room to spend.
AMPLE_SLACK_FRAC = 0.15


def _pace(weekly: Optional[dict]) -> dict:
    """Reset-anchored pacing numbers from the weekly ccusage window."""
    out = {
        "pct": None, "used": None, "limit": None, "remaining": None,
        "hours_to_reset": None, "slack_frac": None,
    }
    if not weekly or not weekly.get("max20x_limit_tokens"):
        return out
    limit = weekly["max20x_limit_tokens"]
    used = weekly.get("tokens", 0)
    out["limit"] = limit
    out["used"] = used
    out["pct"] = 100.0 * used / limit
    out["remaining"] = max(0, limit - used)
    try:
        start = datetime.fromisoformat(weekly["window_start"])
        end = datetime.fromisoformat(weekly["window_end"])
        now = datetime.now(start.tzinfo)
        total = (end - start).total_seconds()
        out["hours_to_reset"] = max(0.0, (end - now).total_seconds() / 3600)
        if total > 0:
            elapsed = max(0.0, min(1.0, (now - start).total_seconds() / total))
            on_pace = limit * elapsed          # steady-spend target by now
            out["slack_frac"] = (on_pace - used) / limit  # >0 = behind pace
    except (ValueError, KeyError, TypeError):
        pass
    return out


def verdict(weekly: Optional[dict] = None, block: Optional[dict] = None,
            hw: Optional[dict] = None) -> dict:
    """Compute the agency verdict. Args can be injected to avoid re-running
    ccusage (e.g. /headroom passes the values it already fetched)."""
    if weekly is None:
        weekly = ccusage.weekly_anchored()
    if hw is None:
        hw = latest_hardware_sample() or {}

    p = _pace(weekly)
    reasons: list[str] = []

    # ---- token room ----
    if p["pct"] is None:
        token_room = "unknown"
        reasons.append("token usage unknown (ccusage unavailable) — pacing conservatively")
    elif p["pct"] >= WEEKLY_HOLD_PCT:
        token_room = "blocked"
        reasons.append(f"weekly budget {p['pct']:.0f}% spent — hold to avoid exhausting quota")
    elif (p["slack_frac"] or 0) > AMPLE_SLACK_FRAC or p["pct"] < 50:
        token_room = "ample"
        if (p["slack_frac"] or 0) > AMPLE_SLACK_FRAC and p["hours_to_reset"] is not None:
            reasons.append(
                f"behind pace by {p['slack_frac']*100:.0f}% of weekly budget with "
                f"{p['hours_to_reset']:.0f}h to reset — spend it before it resets"
            )
        else:
            reasons.append(f"only {p['pct']:.0f}% of weekly budget spent — room to spend")
    elif p["pct"] < 75:
        token_room = "moderate"
        reasons.append(f"weekly budget {p['pct']:.0f}% spent — moderate room")
    else:
        token_room = "tight"
        reasons.append(f"weekly budget {p['pct']:.0f}% spent — getting tight")

    # ---- hardware room ----
    cpu = hw.get("cpu_percent")
    ram = hw.get("ram_percent")
    gpu = hw.get("gpu_util_pct")
    disk_free = hw.get("disk_free_gb")
    gpu_free = gpu is None or gpu < GPU_BUSY_PCT
    busy = [n for n, v in (("CPU", cpu), ("RAM", ram), ("GPU", gpu))
            if v is not None and v >= BUSY_PCT]
    if disk_free is not None and disk_free < MIN_DISK_FREE_GB:
        hw_room = "blocked"
        reasons.append(f"only {disk_free:.0f}GB disk free (< {MIN_DISK_FREE_GB:.0f}GB) — hold")
    elif busy:
        hw_room = "busy"
        reasons.append(f"{', '.join(busy)} ≥ {BUSY_PCT:.0f}% utilized — share the box, go gently")
    else:
        hw_room = "free"
        reasons.append("CPU/RAM/GPU below 50% — resources idle")

    # ---- schedule awareness (advisory; never changes the verdict letter) ----
    schedule = _schedule_context(hw)
    if schedule.get("running"):
        names = ", ".join(r["unit"] for r in schedule["running"][:3])
        reasons.append(f"tracked job(s) running now: {names} — their footprint is already in the numbers above")
    nxt = schedule.get("next_gpu")
    if nxt and nxt["starts_in_min"] <= IMMINENT_MIN:
        reasons.append(
            f"{nxt['unit']} starts in ~{nxt['starts_in_min']:.0f} min (VRAM ~{nxt['vram_gb']:.1f} GB, "
            f"~{nxt['duration_min']:.0f} min) — keep new GPU work short or start after ~{nxt['ends_at_hm']} UTC"
        )
    elif nxt:
        reasons.append(f"GPU quiet until {nxt['starts_at_hm']} UTC ({nxt['starts_in_min'] / 60:.1f}h) — {nxt['unit']} next")

    # ---- combine ----
    if token_room == "blocked" or hw_room == "blocked":
        v, agg = "hold", "none"
    elif token_room == "ample" and hw_room == "free":
        v, agg = "go", "high"
    elif token_room in ("ample", "moderate") and hw_room in ("free", "busy"):
        v, agg = ("go", "normal") if hw_room == "free" else ("slow", "low")
    elif token_room == "tight" or hw_room == "busy":
        v, agg = "slow", "low"
    else:
        v, agg = "slow", "normal"

    # Advisory soft budget for this session: the slack (tokens you're behind
    # pace), capped at what remains. None when unknown.
    suggested = None
    if p["remaining"] is not None:
        slack_tokens = int((p["slack_frac"] or 0) * (p["limit"] or 0))
        suggested = max(0, min(p["remaining"], slack_tokens)) if slack_tokens > 0 else 0

    pieces = []
    if p["pct"] is not None:
        pieces.append(f"{p['pct']:.0f}% weekly used")
    if p["hours_to_reset"] is not None:
        pieces.append(f"{p['hours_to_reset']:.0f}h to reset")
    pieces.append("resources idle" if hw_room == "free" else f"resources {hw_room}")
    headline = f"{v.upper()} ({agg}) — " + ", ".join(pieces)

    return {
        "verdict": v,
        "aggressiveness": agg,
        "headline": headline,
        "reasons": reasons,
        "weekly": p,
        "hardware": {
            "cpu_pct": cpu, "ram_pct": ram, "gpu_pct": gpu,
            "gpu_free": gpu_free, "disk_free_gb": disk_free,
            "gpu_free_until": (schedule.get("next_gpu") or {}).get("starts_at"),
        },
        "schedule": schedule,
        "suggested_session_tokens": suggested,
    }


def _schedule_context(hw: Optional[dict]) -> dict:
    """Running tracked jobs + the next scheduled GPU job, from the job
    ledger. Pure sqlite reads; empty dict if the ledger is unavailable."""
    try:
        from . import jobs
        now = jobs._now()
        wins = jobs.forecast(48, now=now)
    except Exception:
        return {}
    running = [{"unit": w.unit, "since": jobs._iso(w.start), "expected_end": jobs._iso(w.end),
                "vram_gb": w.footprint.vram_gb, "ram_gb": w.footprint.ram_gb}
               for w in wins if w.kind == "running"]
    gpu_wins = [w for w in wins if w.kind != "running" and "gpu" in w.footprint.klass and w.start > now]
    nxt = None
    if gpu_wins:
        w = min(gpu_wins, key=lambda w: w.start)
        nxt = {"unit": w.unit, "starts_at": jobs._iso(w.start), "starts_at_hm": w.start.strftime("%H:%M"),
               "ends_at": jobs._iso(w.end), "ends_at_hm": w.end.strftime("%H:%M"),
               "starts_in_min": (w.start - now).total_seconds() / 60,
               "duration_min": (w.end - w.start).total_seconds() / 60,
               "vram_gb": w.footprint.vram_gb, "ram_gb": w.footprint.ram_gb}
    return {"running": running, "next_gpu": nxt}
