---
kind: decision
slug: schedule-aware-headroom
date: "2026-09-16"
status: accepted
supersedes: "the coordinator admission layer removed 2026-08-01"
---

# 0001 — Schedule-aware headroom: a passive job ledger, not an admission gate

## Context

The box runs a fleet of timer-driven jobs (nightly GPU retrains, data
harvests, monitors) alongside interactive and autonomous Claude sessions.
Agents starting a long GPU/CPU run had no way to know what would start in
the next hour, so collisions happened: on one Sunday two GPU retrains
overlapped and VRAM hit 14.3 of 16 GB. The 30 s hardware poller made the
collision visible after the fact only.

An earlier attempt (the `/plan` admission layer, deleted 2026-08-01) asked
agents to *declare* jobs with estimated tokens/VRAM and gated them. Three
months of telemetry showed one declared job ever. Opt-in declaration
does not survive contact with real workflows.

## Decision

Build the awareness layer so that **it costs the agent nothing**:

1. **Inventory is derived, not declared.** `systemctl list-timers` (user +
   system) and the user crontab are the source of truth. The poller
   refreshes it every tick; occurrences for the next 7 days are cached
   (systemd-analyze for OnCalendar, croniter for cron).
2. **Footprints are learned passively.** The existing poller reads cgroup
   v2 accounting (`cpu.stat`, `memory.current`, `memory.peak`) for every
   running tracked unit and attributes NVML per-process VRAM to units via
   `/proc/<pid>/cgroup`. Start/finish/result/CPU-time are back-filled from
   journal lifecycle events (MESSAGE_ID catalog), so history exists on
   day one. Profiles are p90 over the newest successful runs.
3. **Forecast + window search, advisory only.** `forecast` composes
   occurrences × footprints × running jobs; `window` finds the earliest
   start where a requested envelope fits with margins. Nothing blocks.
4. **Surfaces are automatic.** The session-start hook prints a 4–6 line
   "Box schedule" notice in every session; `/headroom` repeats it; the
   agency verdict gains a `schedule` block and an "imminent GPU job"
   reason. The dashboard gets `/jobs` with a timeline.
5. **Ad-hoc runs can opt in cheaply.** `claude-coordinator-jobs run`
   wraps a command in a transient user unit so it is attributed and
   visible to other sessions. It is the recommended launcher for runs
   longer than ~30 min, but not required.

## Consequences

- Hardware-sample retention rises from 7 to 30 days (~90k rows) so
  footprints can be learned across a month.
- The poller tick gains ~50 ms (a few `systemctl` calls and cgroup file
  reads); journal catch-up runs every 10 min.
- A useful by-product: repeated failures of scheduled jobs are now
  visible (`health`, dashboard banner) — several had been failing
  silently for days.
- `~/.claude/jobs.yaml` is the only hand-maintained input, and it is
  optional (labels, ignore flags, expected envelopes for new jobs).
- If the layer stops being consulted, telemetry will show it (the
  `job_declared` table for `run`, the reasons in agency verdicts); the
  removal path is the same as the 2026-08-01 one.
