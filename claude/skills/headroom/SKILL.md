---
name: headroom
description: Print a formatted summary of Claude token usage (5h block / reset-anchored weekly), hardware state (CPU/RAM/GPU/disk), and the agency verdict. Sub-second. Cheap to run often. Reads from ~/.claude/state.db — no writes. Renamed from /status to avoid collision with the built-in /status slash command.
---

# headroom

Fast read-only snapshot of the resource coordinator. Use it before
starting any non-trivial work, and any time you want to know "what
headroom do I have right now?"

## When to use

- Before `/implement`, `/iterate`, `/ingest`, `/digest`, or any loop —
  check token-window usage and GPU availability.
- When a subagent has been churning and you want to see where you sit.

## How

Shell out to the coordinator CLI:

```bash
~/claude-system/coordinator/.venv/bin/claude-coordinator-status
```

Pass `--json` for structured output (useful when composing with other
skills):

```bash
~/claude-system/coordinator/.venv/bin/claude-coordinator-status --json
```

## What it shows

- **Claude quota (via `ccusage`)** — reads per-message `usage` blocks
  from `~/.claude/projects/*/*.jsonl` and aggregates over two windows:
  the active 5h billing block, and the reset-anchored weekly window
  (since the last Mon 17:00 local — the same boundary claude.ai uses).
  Reports tokens, cost, burn rate, projected end-of-block usage, and
  percentage against the Max-20x ceiling for each window. Falls back
  to a local Stop-hook accumulator if `ccusage` isn't on PATH.
- **Hardware (latest sample)** — CPU / RAM / disk on `/mnt/projects` /
  GPU utilization + VRAM + temperature + power. Sampled every 30s by
  the `claude-hw-poller.timer` systemd unit.
- **Agency verdict** — GO/SLOW/HOLD with reasons and a suggested
  session token budget (drives `agency: max` repos).

## ccusage dependency

The quota section shells out to `ccusage` (Node.js CLI). Install once:

```bash
npm i -g ccusage
npm update -g ccusage   # occasionally, to track upstream
```

Both ccusage calls run concurrently with `--offline` (skips pricing
fetch) and a 3s timeout each. If `ccusage` is missing or hangs, the
coordinator falls back to the legacy Stop-hook accumulator silently.

Anthropic doesn't publish exact Max-20x quota numbers. Both ceilings
live in `coordinator/coordinator/ccusage.py`:

- `MAX_20X_WEEKLY_TOKEN_LIMIT` ≈ 2.31B. **Well-calibrated** from a
  reset-anchored 4-day window on 2026-05-22 (231M tokens = 10% used).
  /headroom's weekly % now matches claude.ai to within ~0.1pp.
- `MAX_20X_5H_TOKEN_LIMIT` ≈ 184M. **Poorly calibrated.** Two data
  points (2026-05-13: 3% at 5.5M, 2026-05-22: 3% at 27.7M) disagree
  by 5x because ccusage's block boundary is hour-rounded while
  Anthropic anchors to your actual first message — so a chunk of
  ccusage's "active block" can belong to a *previous* claude.ai
  session. The displayed 5h % can underestimate by ~2-3x. Treat as
  a rough lower bound; the projection/burn-rate fields are more
  useful than the headline %.

Recalibrating the **weekly** number: read claude.ai's weekly %, run
`/headroom --json | jq .ccusage_weekly.tokens`, divide tokens by
(pct / 100), update the constant. The longer the window the cleaner
the signal — late-week snapshots are best.

The 5h calibration is genuinely hard without identifying the true
claude.ai session boundary. Don't trust the 5h ceiling for budgeting;
use the projection field instead.

## Troubleshooting

- "no samples yet" under Hardware → `systemctl --user status
  claude-hw-poller.timer`. Re-enable with `systemctl --user enable
  --now claude-hw-poller.timer`.
- "ccusage not installed" note → run the install command above.
- Slow (>1s) → likely a cold `ccusage` invocation; warm runs are
  ~0.5s. If persistent, check `du -sh ~/.claude/state.db` and verify
  `prune_hardware_samples` runs (it does on every poller tick).
