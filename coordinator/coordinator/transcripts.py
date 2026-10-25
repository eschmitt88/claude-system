"""Direct reader for per-message usage in ~/.claude/projects/**/*.jsonl.

ccusage aggregates into hour-rounded 5h blocks and day-granular `--since`
filters, which can't answer "what was spent between 14:02:17 and now?".
The quota anchor (ratelimits.py) needs exactly that, so this module scans
the transcripts itself: only files touched since t0, only lines carrying
a `usage` block, deduped on (message.id, requestId) the way ccusage does
(duplicate records of one response carry identical usage).

Cost is priced from PRICING_PER_MTOK. It does not have to match an
invoice — calibrate.py divides it by Anthropic's observed % to get the
ceiling in these same units — but per-model cache-read rates matter:
they differ by model and dominate cache-heavy agentic traffic.
"""
from __future__ import annotations

import bisect
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECTS_DIR = Path(
    os.environ.get("CLAUDE_PROJECTS_DIR") or Path.home() / ".claude" / "projects"
)

# $/MTok: input, output, cache read, cache write 5m, cache write 1h.
# Matched by longest model-id prefix. Cache writes are 1.25x (5m) / 2x
# (1h) input; cache reads are 0.1x input except where a model's price
# list says otherwise (Fable 5.1, Opus 5.5).
PRICING_PER_MTOK = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "claude-mythos-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "claude-fable-5": (10.0, 50.0, 1.00, 12.5, 20.0),
    "claude-mythos-5": (10.0, 50.0, 1.00, 12.5, 20.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0, 8.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-opus-4": (5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5, 4.0),
    "claude-sonnet-4": (3.0, 15.0, 0.30, 3.75, 6.0),
    "claude-haiku-4": (1.0, 5.0, 0.10, 1.25, 2.0),
}
_PREFIXES = sorted(PRICING_PER_MTOK, key=len, reverse=True)
# Fast mode bills 2x the standard rates.
_FAST_MULTIPLIER = 2.0


def _rates(model: str) -> Optional[tuple]:
    for p in _PREFIXES:
        if model.startswith(p):
            return PRICING_PER_MTOK[p]
    return None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    unpriced_tokens: int = 0  # tokens from models missing in PRICING_PER_MTOK
    n_messages: int = 0
    models: set = field(default_factory=set)

    @property
    def tokens(self) -> int:
        return (self.input_tokens + self.output_tokens
                + self.cache_read_tokens + self.cache_creation_tokens)


@dataclass
class Record:
    ts: float  # unix seconds
    tokens: int
    cost_usd: float
    cache_read_tokens: int


def _parse_ts(raw: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def _record(d: dict, usage: Usage) -> Optional[Record]:
    """Fold one transcript line into `usage`; return its Record."""
    msg = d.get("message") or {}
    u = msg.get("usage")
    if not isinstance(u, dict):
        return None
    inp = u.get("input_tokens") or 0
    out = u.get("output_tokens") or 0
    cr = u.get("cache_read_input_tokens") or 0
    cc = u.get("cache_creation_input_tokens") or 0
    if not (inp or out or cr or cc):
        # Rare records keep their counts only under `iterations`.
        for it in u.get("iterations") or []:
            inp += it.get("input_tokens") or 0
            out += it.get("output_tokens") or 0
            cr += it.get("cache_read_input_tokens") or 0
            cc += it.get("cache_creation_input_tokens") or 0
    tokens = inp + out + cr + cc
    if not tokens:
        return None
    split = u.get("cache_creation") or {}
    cc_1h = split.get("ephemeral_1h_input_tokens") or 0
    cc_5m = max(0, cc - cc_1h)

    model = msg.get("model") or ""
    rates = _rates(model)
    cost = 0.0
    if rates:
        r_in, r_out, r_cr, r_5m, r_1h = rates
        cost = (inp * r_in + out * r_out + cr * r_cr
                + cc_5m * r_5m + cc_1h * r_1h) / 1_000_000
        if u.get("speed") == "fast":
            cost *= _FAST_MULTIPLIER
    else:
        usage.unpriced_tokens += tokens

    usage.input_tokens += inp
    usage.output_tokens += out
    usage.cache_read_tokens += cr
    usage.cache_creation_tokens += cc
    usage.cost_usd += cost
    usage.n_messages += 1
    if model:
        usage.models.add(model)
    return Record(ts=0.0, tokens=tokens, cost_usd=cost, cache_read_tokens=cr)


def scan(t0: datetime, t1: Optional[datetime] = None) -> tuple[Usage, list[Record]]:
    """All usage with t0 < timestamp <= t1 (t1 = now), plus the per-message
    records sorted by time (for prefix sums in calibrate.py)."""
    lo = t0.timestamp()
    hi = (t1 or datetime.now(timezone.utc)).timestamp()
    usage = Usage()
    records: list[Record] = []
    seen: set = set()
    for path in PROJECTS_DIR.glob("**/*.jsonl"):
        try:
            if path.stat().st_mtime < lo:
                continue
            fh = path.open("rb")
        except OSError:
            continue
        with fh:
            for line in fh:
                if b'"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = _parse_ts(d.get("timestamp") or "")
                if ts is None or ts <= lo or ts > hi:
                    continue
                key = ((d.get("message") or {}).get("id"), d.get("requestId"))
                if key[0] and key in seen:
                    continue
                seen.add(key)
                rec = _record(d, usage)
                if rec is not None:
                    rec.ts = ts
                    records.append(rec)
    records.sort(key=lambda r: r.ts)
    return usage, records


def usage_between(t0: datetime, t1: Optional[datetime] = None) -> Usage:
    return scan(t0, t1)[0]


class CumulativeCost:
    """Prefix sums over scan() records: cost/tokens spent up to any time."""

    def __init__(self, records: list[Record]):
        self.ts = [r.ts for r in records]
        self.cost = []
        self.cache_read = []
        self.tokens = []
        c = cr = t = 0.0
        for r in records:
            c += r.cost_usd
            cr += r.cache_read_tokens
            t += r.tokens
            self.cost.append(c)
            self.cache_read.append(cr)
            self.tokens.append(t)

    def at(self, ts: float) -> tuple[float, float, float]:
        """(cost, tokens, cache_read_tokens) summed over records <= ts."""
        i = bisect.bisect_right(self.ts, ts)
        if i == 0:
            return 0.0, 0.0, 0.0
        return self.cost[i - 1], self.tokens[i - 1], self.cache_read[i - 1]
