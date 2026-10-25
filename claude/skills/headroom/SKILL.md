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

- **Claude quota** — two windows (current 5h session, weekly). Preferred
  basis is **Anthropic's own %**: Claude Code hands it to the status line
  (`claude/hooks/statusline.sh`), which stores the newest reading in
  `~/.claude/state/rate-limits.json`; /headroom shows
  `reported % + spend since that reading / ceiling`, with exact window
  bounds from Anthropic's `resets_at`. Spend is read straight from
  `~/.claude/projects/**/*.jsonl` (`coordinator/transcripts.py`).
  Without a reading it falls back to `ccusage` against static ceilings.
- **Hardware (latest sample)** — CPU / RAM / disk on `/mnt/projects` /
  GPU utilization + VRAM + temperature + power. Sampled every 30s by
  the `claude-hw-poller.timer` systemd unit.
- **Scheduled jobs** — the box-schedule brief from the job ledger:
  tracked jobs running now (with footprint and expected end), heavy
  jobs due in the next 12h, when the GPU is next claimed, and any job
  failing repeatedly. `/jobs` has the full inventory, forecast and
  window search.
- **Agency verdict** — GO/SLOW/HOLD with reasons and a suggested
  session token budget (drives `agency: max` repos). Includes a
  schedule reason when a GPU job is imminent (≤45 min).

## Where the numbers come from

- **Readings** only arrive from *interactive* sessions (headless
  `claude -p` never renders a status line). Between readings, spend
  since the last one is added; the anchor line shows its age and is
  flagged stale after 24h.
- **Ceilings are self-calibrating.** Every changed reading is logged to
  `~/.claude/state/rate-limits.ndjson`; `calibrate.py` (run by the
  poller, ≤ every 15 min, or `claude-coordinator-calibrate`) fits
  `L = window spend / reported %` per window (readings ≥ 20% only) into
  `~/.claude/state/quota-calibration.json`. Bonus weeks are absorbed
  automatically — no manual recalibration or override files.
- **Fallback** (no reading in the current window): calibrated ceiling
  if one exists, else `ccusage` vs the static `QUOTA_*` values in
  `~/.claude/.env` (and the legacy override files). `npm i -g ccusage`
  is only needed for this path.

## Troubleshooting

- "no samples yet" under Hardware → `systemctl --user status
  claude-hw-poller.timer`. Re-enable with `systemctl --user enable
  --now claude-hw-poller.timer`.
- "no status-line reading yet" note → open/answer any interactive
  session; check `jq . ~/.claude/state/rate-limits.json`.
- Slow (>1s) → likely a cold `ccusage` invocation; warm runs are
  ~0.5s. If persistent, check `du -sh ~/.claude/state.db` and verify
  `prune_hardware_samples` runs (it does on every poller tick).
