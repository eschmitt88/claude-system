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
import os
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

# Weekly Max-20x ceiling, cost-anchored. Reset-anchored calibration
# history (user-reported claude.ai % vs summed window usage):
#   2026-05-22: 231.0M tok           = 10% → ~2.31B tok/week (Opus-era mix)
#   2026-07-15: 513.08M tok, $200.39 = 53% → ~968M tok/week, ~$378/week
#   2026-07-23: 703.44M tok, $363.19 = 35% → ~$1038/week implied. User
#     reports a temporary +50% bonus this week; even so the bonus-free
#     implied ceiling would be ~$692 — ~1.8x the 07-15 calibration.
#     Handled for now via the weekly-limit override file (below) expiring
#     at the 07-27 reset; RECALIBRATE against claude.ai early next window
#     to see where the base constant really sits.
# The token-implied ceiling moved ~2.4x between the two points, consistent
# with Fable 5 costing 2x Opus per token — Anthropic's quota is evidently
# **cost-weighted**, so the USD ceiling is the model-mix-stable constant
# and the primary basis for the weekly %. The token constant below is the
# 2026-07-15 mix's equivalent, kept only as a fallback for windows where
# ccusage can't price the blocks (all-unknown-model mix). Recalibrate both
# whenever the dashboard % drifts from claude.ai's displayed %.
MAX_20X_WEEKLY_COST_LIMIT_USD = 378.0
MAX_20X_WEEKLY_TOKEN_LIMIT = 968_000_000

# Anthropic resets the weekly quota at Mon 17:00 in the user's local TZ
# (displayed on claude.ai/settings/usage). System runs in UTC; if the
# user's claude.ai browser sits in a different TZ, the boundary will be
# off by their offset. Keep this aligned with the user's display.
_WEEKLY_RESET_HOUR_LOCAL = 17
_WEEKLY_RESET_WEEKDAY = 0  # Monday

# Anthropic occasionally issues out-of-band quota resets (goodwill /
# incident credits) that zero the counter between scheduled boundaries
# (first observed 2026-07-16). Record one by writing its ISO-8601
# timestamp to this file:  date -Iseconds > ~/.claude/quota-reset-override
# The window start uses it whenever it is more recent than the scheduled
# anchor; it goes inert automatically once the next scheduled reset
# passes, so the file never needs cleanup.
_RESET_OVERRIDE_FILE = Path(
    os.environ.get("QUOTA_RESET_OVERRIDE_FILE")
    or Path.home() / ".claude" / "quota-reset-override"
)


# Anthropic also occasionally grants temporary extra weekly quota (bonus
# tokens — first observed week of 2026-07-20, when claude.ai showed 35%
# at a spend our calibration scored as 96%). Record the corrected weekly
# USD ceiling and when it stops applying:
#   echo "1038 2026-07-27T17:00:00-07:00" > ~/.claude/quota-weekly-limit-override
# (limit_usd, then ISO-8601 expiry — normally the next scheduled reset).
# The override is ignored once the expiry passes, so it never needs
# cleanup. Derive the value from a live claude.ai reading:
#   limit_usd = window_cost_usd / (claude_ai_pct / 100).
_WEEKLY_LIMIT_OVERRIDE_FILE = Path(
    os.environ.get("QUOTA_WEEKLY_LIMIT_OVERRIDE_FILE")
    or Path.home() / ".claude" / "quota-weekly-limit-override"
)


def _weekly_limit_override() -> Optional[float]:
    try:
        parts = _WEEKLY_LIMIT_OVERRIDE_FILE.read_text().split()
    except OSError:
        return None
    if len(parts) != 2:
        return None
    try:
        limit = float(parts[0])
        expiry = datetime.fromisoformat(parts[1])
    except ValueError:
        return None
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=datetime.now().astimezone().tzinfo)
    if limit <= 0 or datetime.now(timezone.utc) >= expiry:
        return None
    return limit


def _reset_override() -> Optional[datetime]:
    try:
        raw = _RESET_OVERRIDE_FILE.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


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


def _weekly_window() -> tuple[datetime, datetime]:
    """Current quota window as (last reset, next reset), tz-aware.

    Start is the most recent scheduled Mon-17:00-local boundary, unless an
    out-of-band reset override (see _RESET_OVERRIDE_FILE) is more recent.
    End stays on the scheduled cadence — an out-of-band reset zeroes the
    counter but does not move the reset day shown on claude.ai (if one
    ever does, update the schedule constants, not the override)."""
    now_local = datetime.now().astimezone()
    days_back = (now_local.weekday() - _WEEKLY_RESET_WEEKDAY) % 7
    scheduled = datetime.combine(
        (now_local - timedelta(days=days_back)).date(),
        time(_WEEKLY_RESET_HOUR_LOCAL, 0),
        tzinfo=now_local.tzinfo,
    )
    if scheduled > now_local:
        scheduled -= timedelta(days=7)
    start = scheduled
    override = _reset_override()
    if override is not None and scheduled < override <= now_local:
        start = override
    return start, scheduled + timedelta(days=7)


def weekly_anchored() -> Optional[dict]:
    """Sum tokens since the last quota reset (scheduled Mon 17:00 local,
    or an out-of-band override) — matches claude.ai's weekly-quota window.
    Returns None on failure.

    We pull `ccusage blocks --json` and filter to blocks whose startTime
    falls on/after the cutoff. This is more accurate than `daily --since`
    because daily aggregates by calendar day (which doesn't align with
    the 17:00-local reset)."""
    raw = _run(["blocks"])
    if not raw:
        return None
    cutoff, next_reset = _weekly_window()
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

    now_local = datetime.now().astimezone()
    remaining_hours = max(0, int((next_reset - now_local).total_seconds() // 3600))

    # Cost is the quota's real currency (see calibration note above). When
    # the window has priced usage, the % is cost-based and the token limit
    # reported to callers is the *effective* one for this window's mix
    # (tokens × cost_limit / cost) — that keeps token-space consumers
    # (agency pacing, suggested_session_tokens) consistent with the %.
    # Unpriced windows fall back to the static token calibration.
    override = _weekly_limit_override()
    cost_limit = override if override is not None else MAX_20X_WEEKLY_COST_LIMIT_USD
    # Scale the token fallback by the same factor so both bases agree.
    token_limit = int(MAX_20X_WEEKLY_TOKEN_LIMIT * cost_limit / MAX_20X_WEEKLY_COST_LIMIT_USD)
    if cost > 0 and total > 0:
        pct = 100.0 * cost / cost_limit
        effective_token_limit = int(total * cost_limit / cost)
        limit_basis = "cost"
    else:
        pct = 100.0 * total / token_limit
        effective_token_limit = token_limit
        limit_basis = "tokens"
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
        "max20x_limit_tokens": effective_token_limit,
        "max20x_limit_cost_usd": cost_limit,
        "pct_vs_max20x_limit": pct,
        "limit_basis": limit_basis,
        "limit_override_active": override is not None,
    }
