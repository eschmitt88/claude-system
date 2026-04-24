---
name: status
description: Print a formatted summary of Claude token usage (5h / 7d), hardware state (CPU/RAM/GPU/disk), and the coordinator job queue. Sub-second. Cheap to run often. Reads from ~/.claude/state.db — no writes.
---

# status

Fast read-only snapshot of the resource coordinator. Use it before
starting any non-trivial work, and any time you want to know "what
headroom do I have right now?"

## When to use

- Before `/implement`, `/iterate`, `/ingest`, `/digest`, or any loop —
  check token-window usage and GPU availability.
- When a subagent has been churning and you want to see where you sit.
- As part of `/plan`'s output.

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

- **Claude quota (observed)** — sum of `input_tokens + output_tokens +
  cache_creation_tokens` from Stop-hook events over the trailing 5h
  and 7d windows. This is a **local accumulator**, not Anthropic's
  true quota window. Use `ccusage` for reset times — the quota window
  boundary isn't exposed through any API.
- **Hardware (latest sample)** — CPU / RAM / disk on `/mnt/projects` /
  GPU utilization + VRAM + temperature + power. Sampled every 30s by
  the `claude-hw-poller.timer` systemd unit.
- **Jobs** — running and queued jobs declared by earlier skill
  invocations.
- **Recent completed (last 5)** — with estimated-vs-actual token
  delta so you can tell whether your estimates are calibrated.

## Troubleshooting

- "no samples yet" under Hardware → `systemctl --user status
  claude-hw-poller.timer`. Re-enable with `systemctl --user enable
  --now claude-hw-poller.timer`.
- "0 total" under Claude quota → Stop hook hasn't fired since schema
  init. Every session close now writes a row; your first real
  session after Phase 6 install populates it.
- Slow (>1s) → state.db is unexpectedly large. Check
  `du -sh ~/.claude/state.db` and verify `prune_hardware_samples`
  runs (it does on every poller tick).
