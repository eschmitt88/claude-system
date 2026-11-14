---
name: headroom
description: Sub-second, read-only snapshot of Claude quota (5h and weekly), hardware (CPU/RAM/GPU/disk), the box schedule and the agency verdict. Run before any non-trivial compute or token spend.
---

# headroom

```bash
~/claude-system/coordinator/.venv/bin/claude-coordinator-status [--json]
```

- **Claude quota**, 5h and weekly. The basis is Anthropic's own %, which
  Claude Code passes to the status line (`hooks/statusline.sh` stores the
  newest reading); the display is that reading plus spend since, read from
  the session transcripts. Readings only arrive from interactive sessions,
  so the anchor line shows its age and is flagged stale after 24h.
  Ceilings calibrate themselves from logged readings (bonus weeks
  included). With no reading in the window it falls back to the calibrated
  ceiling, then to `ccusage` against the static `QUOTA_*` values in
  `~/.claude/.env`.
- **Hardware**: the latest 30-second sample from `claude-hw-poller.timer`.
- **Scheduled jobs**: the box-schedule brief. `/jobs` has the detail.
- **Agency verdict**: GO / SLOW / HOLD with reasons and a suggested session
  budget. It drives `agency: max` repos
  (`~/claude-system/claude/rules/agency.md`).

If something looks wrong: "no samples yet" means the poller timer is down
(`systemctl --user enable --now claude-hw-poller.timer`); "no status-line
reading yet" clears once any interactive session answers
(`jq . ~/.claude/state/rate-limits.json`).
