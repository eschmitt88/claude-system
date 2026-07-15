"""Wraps the external `ccusage` CLI to read per-message token usage from
`~/.claude/projects/*/*.jsonl`.

ccusage is the de-facto community tool for Claude Code usage; it handles
the rolling 5h "session block" boundary that Anthropic's quota window
follows (anchored to the first message in the block). We shell out instead
of re-implementing because the block-rotation edge cases drift.

All calls use `--offline` to skip pricing-API fetches. Each call is bounded
by `_TIMEOUT_S` so a hung ccusage can't stall /headroom.

Returns None on any failure (binary missing, parse error, timeout) so
callers can degrade to the state.db-only path.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

_TIMEOUT_S = 8
_BIN = "ccusage"
# systemd user services get the stock PATH (/usr/bin:...), which does not
# include the npm global prefix where ccusage lives — shutil.which() fails
# there even though the binary is installed. Fall back to the known install
# location so the dashboard service and cron-spawned coordinators find it.
_BIN_FALLBACKS = (Path.home() / ".npm-global" / "bin" / "ccusage",)

# ccusage --offline prices from a bundled LiteLLM snapshot that (as of
# ccusage 20.x) has no entry for claude-fable-5, so Fable-only blocks come
# back with costUSD 0. Estimate those locally. Rates are per MTok from the
# published price list: Fable 5 is $10 in / $50 out (2x Opus 4.8's $5/$25);
# cache read is 0.1x input, cache write (5m TTL) is 1.25x input.
_FALLBACK_PRICING_PER_MTOK = {
    "claude-fable-5": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.0,
        "cache_creation": 12.5,
    },
}


def _resolve_bin() -> Optional[str]:
    found = shutil.which(_BIN)
    if found:
        return found
    for p in _BIN_FALLBACKS:
        if p.is_file():
            return str(p)
    return None


def _estimate_cost(counts: dict, models: list) -> Optional[float]:
    """Cost estimate for a block ccusage priced at 0 because its offline
    table doesn't know the model(s). Only returns a number when every model
    in the block has a fallback entry — a mixed known/unknown block would
    have costUSD > 0 already and never reaches this path."""
    if not models or not all(m in _FALLBACK_PRICING_PER_MTOK for m in models):
        return None
    # Per-model token splits aren't exposed per block; with a single
    # fallback model (the normal case) this is exact.
    rates = _FALLBACK_PRICING_PER_MTOK[models[0]]
    return (
        counts.get("inputTokens", 0) * rates["input"]
        + counts.get("outputTokens", 0) * rates["output"]
        + counts.get("cacheReadInputTokens", 0) * rates["cache_read"]
        + counts.get("cacheCreationInputTokens", 0) * rates["cache_creation"]
    ) / 1_000_000

# 5h Max-20x ceiling — known to be poorly calibrated because ccusage's
# block window does not align with claude.ai's "current session" window
# (ccusage rounds the block start to top-of-hour; Anthropic anchors to
# first message of session, which can sit anywhere in the hour). At the
# 2026-05-22 data point claude.ai showed 3% used while ccusage's active
# block was at 27.7M tokens, which implies a ~923M ceiling — but a
# meaningful fraction of those tokens fell in a *previous* claude.ai
# session whose tail bled into ccusage's current block. The 2026-05-13
# data point (3% at 5.53M) implied ~184M. Until we can identify the true
# session boundary, this number is a rough lower bound; the displayed
# 5h % can underestimate by ~2-3x in practice.
MAX_20X_5H_TOKEN_LIMIT = 184_000_000

# Weekly Max-20x ceiling in ccusage tokens. Reset-anchored calibration
# history (user-reported claude.ai % vs summed window tokens):
#   2026-05-22: 231.0M  = 10% → ~2.31B/week (Opus-era model mix)
#   2026-07-15: 513.08M = 53% → ~968M/week  (Fable-5-dominant mix)
# The implied ceiling moved ~2.4x between the two points, consistent with
# Fable 5 costing 2x Opus per token — the underlying quota is almost
# certainly cost-weighted, so this token-denominated constant is only
# valid for the current model mix. (Cost cross-check at the 2026-07-15
# point: $200.39 window cost = 53% → implied ~$378/week if cost-anchored.)
# Recalibrate whenever the dashboard % drifts from claude.ai's displayed %.
MAX_20X_WEEKLY_TOKEN_LIMIT = 968_000_000

# Anthropic resets the weekly quota at Mon 17:00 in the user's local TZ
# (displayed on claude.ai/settings/usage). System runs in UTC; if the
# user's claude.ai browser sits in a different TZ, the boundary will be
# off by their offset. Keep this aligned with the user's display.
_WEEKLY_RESET_HOUR_LOCAL = 17
_WEEKLY_RESET_WEEKDAY = 0  # Monday


def _run(args: list[str]) -> Optional[dict]:
    bin_path = _resolve_bin()
    if bin_path is None:
        return None
    try:
        proc = subprocess.run(
            [bin_path, *args, "--json", "--offline"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def active_block() -> Optional[dict]:
    """Return the currently active 5h billing block, or None.

    Shape of the returned dict (subset of ccusage's payload):
      tokens, cost_usd, models, start_time, end_time, remaining_minutes,
      burn_tokens_per_min, projection_tokens, projection_cost,
      historical_max_tokens (from --token-limit max),
      pct_vs_historical_max (None if no history)
    """
    raw = _run(["blocks", "--active", "--token-limit", "max"])
    if not raw:
        return None
    blocks = raw.get("blocks") or []
    if not blocks:
        return None
    b = blocks[0]
    counts = b.get("tokenCounts") or {}
    burn = b.get("burnRate") or {}
    proj = b.get("projection") or {}
    total = b.get("totalTokens", 0)

    # `--token-limit max` injects a `tokenLimitStatus` block when history exists.
    limit_status = b.get("tokenLimitStatus") or {}
    historical_max = limit_status.get("limit")
    pct_hist = None
    if historical_max and historical_max > 0:
        pct_hist = 100.0 * total / historical_max
    pct_max20x = 100.0 * total / MAX_20X_5H_TOKEN_LIMIT

    # Time remaining: prefer block endTime − now over actualEndTime.
    remaining_min = None
    end = b.get("endTime")
    if end:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            remaining_min = max(0, int((end_dt - datetime.now(timezone.utc)).total_seconds() // 60))
        except ValueError:
            pass

    models = b.get("models") or []
    cost_usd = b.get("costUSD")
    if not cost_usd and total:
        cost_usd = _estimate_cost(counts, models) or cost_usd

    return {
        "tokens": total,
        "input_tokens": counts.get("inputTokens", 0),
        "output_tokens": counts.get("outputTokens", 0),
        "cache_read_tokens": counts.get("cacheReadInputTokens", 0),
        "cache_creation_tokens": counts.get("cacheCreationInputTokens", 0),
        "cost_usd": cost_usd,
        "models": models,
        "start_time": b.get("startTime"),
        "end_time": end,
        "remaining_minutes": remaining_min,
        "burn_tokens_per_min": burn.get("tokensPerMinute"),
        "burn_cost_per_hour": burn.get("costPerHour"),
        "projection_tokens": proj.get("totalTokens"),
        "projection_cost": proj.get("totalCost"),
        "historical_max_tokens": historical_max,
        "pct_vs_historical_max": pct_hist,
        "max20x_limit_tokens": MAX_20X_5H_TOKEN_LIMIT,
        "pct_vs_max20x_limit": pct_max20x,
    }


def _last_weekly_reset() -> datetime:
    """Most recent Mon 17:00 local, as a tz-aware datetime."""
    now_local = datetime.now().astimezone()
    days_back = (now_local.weekday() - _WEEKLY_RESET_WEEKDAY) % 7
    candidate = datetime.combine(
        (now_local - timedelta(days=days_back)).date(),
        time(_WEEKLY_RESET_HOUR_LOCAL, 0),
        tzinfo=now_local.tzinfo,
    )
    if candidate > now_local:
        candidate -= timedelta(days=7)
    return candidate


def weekly_anchored() -> Optional[dict]:
    """Sum tokens since the last Mon 17:00 local — matches claude.ai's
    weekly-quota window. Returns None on failure.

    We pull `ccusage blocks --json` and filter to blocks whose startTime
    falls on/after the cutoff. This is more accurate than `daily --since`
    because daily aggregates by calendar day (which doesn't align with
    the 17:00-local reset)."""
    raw = _run(["blocks"])
    if not raw:
        return None
    cutoff = _last_weekly_reset()
    cutoff_utc = cutoff.astimezone(timezone.utc)

    total = 0
    input_t = output_t = cache_read = cache_create = 0
    cost = 0.0
    n_blocks = 0
    latest_block_end: Optional[datetime] = None

    for b in raw.get("blocks", []):
        if b.get("isGap"):
            continue
        st = b.get("startTime")
        if not st:
            continue
        try:
            sdt = datetime.fromisoformat(st.replace("Z", "+00:00"))
        except ValueError:
            continue
        if sdt < cutoff_utc:
            continue
        tc = b.get("tokenCounts") or {}
        total += b.get("totalTokens", 0)
        input_t += tc.get("inputTokens", 0)
        output_t += tc.get("outputTokens", 0)
        cache_read += tc.get("cacheReadInputTokens", 0)
        cache_create += tc.get("cacheCreationInputTokens", 0)
        block_cost = b.get("costUSD")
        if not block_cost and b.get("totalTokens"):
            block_cost = _estimate_cost(tc, b.get("models") or [])
        cost += block_cost or 0
        n_blocks += 1
        end = b.get("endTime")
        if end:
            try:
                edt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if latest_block_end is None or edt > latest_block_end:
                    latest_block_end = edt
            except ValueError:
                pass

    next_reset = cutoff + timedelta(days=7)
    now_local = datetime.now().astimezone()
    remaining_hours = max(0, int((next_reset - now_local).total_seconds() // 3600))
    return {
        "tokens": total,
        "input_tokens": input_t,
        "output_tokens": output_t,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_create,
        "cost_usd": cost,
        "n_blocks": n_blocks,
        "window_start": cutoff.isoformat(),
        "window_end": next_reset.isoformat(),
        "remaining_hours": remaining_hours,
        "max20x_limit_tokens": MAX_20X_WEEKLY_TOKEN_LIMIT,
        "pct_vs_max20x_limit": 100.0 * total / MAX_20X_WEEKLY_TOKEN_LIMIT,
    }
