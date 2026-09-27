---
kind: decision
slug: capacity-gate
date: "2026-09-22"
status: accepted
builds_on: 0001-schedule-aware-headroom
---

# 0002 — A capacity gate in front of heavy jobs, not a scheduler

## Context

Decision 0001 made the box's schedule visible. Within a week the ledger
showed the same collision twice: a six-hour weekly from-scratch retrain
holding the GPU and ~40 GB of RAM while a daily retrain from a different
project started on top of it at 09:40 and died (RAM 85 of 92 GB). It also
showed one job failing silently every day for eighteen days. Visibility
without enforcement fixes neither.

The obvious enforcement, a queue daemon that jobs register with, is the
shape that already failed here once (the 2026-08 admission layer: opt-in
declaration, never used). Constraints for a second attempt:

- No per-run discipline from agents or humans. If it needs remembering, it
  will not happen.
- No new daemon. systemd is the scheduler and is good at it.
- Small work must never queue behind big work.
- Liveness must be measurable from day one.

## Decision

**1. Gate at the unit, mechanically.** `claude-coordinator-jobs gate` wraps
a unit's `ExecStart` through a generated systemd drop-in
(`<unit>.service.d/50-claude-jobs.conf`, written by `install-gates` from
`~/.claude/jobs.yaml`). The project's unit file is untouched; the drop-in
is a one-time, idempotent change that then holds forever. Ad-hoc agent
runs launched via `run` pass through the same gate.

**2. Capacity-based admission, not a queue.** A job asks whether its
envelope fits in: total capacity, minus an interactive reserve (12 GB RAM,
1 GB VRAM), minus leases held by running jobs, minus the envelopes of
*strictly higher-class* jobs scheduled to start inside its own expected
span. If it fits it takes a lease and runs; otherwise it polls every 45 s.
"Let small things through" is not a special case: a 5-minute ingest fits
beside almost anything and passes immediately.

**3. Envelopes are learned, declaration is an override.** The gate fills
GPU/RAM/cores/duration from the ledger's p90 over live-attributed runs
(anonymous memory, not cache-inclusive cgroup peaks). `expect:` in
`jobs.yaml` seeds a job that has no history yet. Nobody logs their needs;
the poller already measured them.

**4. Three classes, first-come within a class, aging across.**
`production` > `batch` > `agent`. A waiting higher class reserves capacity
against lower-class starters. Same class is first-come, so the Sunday
weekly retrain (already running) wins and the daily retrain waits ~4 h.
After half its `max_wait`, a waiting job stops honouring reservations;
at `max_wait` it applies its policy: `run` anyway (default; production
jobs must happen) or `skip` with a notification (harmless-to-miss batch
work).

**5. Leases close the race the poller cannot.** The lease is written before
the command starts, so two jobs launched within one 30 s poll interval
cannot both see free capacity. The poller expires leases whose gate
process has died (crash, kill, reboot).

**6. Backstops in the unit, not the gate.** The same drop-in carries
`MemoryMax=` (sized from the ledger), `Nice`/`IOWeight` for batch work,
`After=` for the two real dependency pairs, and
`OnFailure=claude-job-failed@%n.service`, a template unit that pushes a
terse ntfy notice. VRAM has no cgroup control; the lease is the only
guard there.

**7. Every decision is recorded.** `gate_events` holds pass / wait /
timeout-run / timeout-skip / expired with the wait time and reason. If it
never waits in three months, the wait logic was unnecessary, but the
wrapper still buys attribution and limits, so it stays.

## Consequences

- The Sunday collision is resolved without editing any timer: the AD
  retrain queues until ~13:30 and runs after the weekly retrain.
- A gate wait keeps the unit in `activating` for its duration. Waiting
  time is recorded separately and excluded from learned durations.
- `MemoryMax=` turns a would-be box-wide OOM into a single failed job
  plus a notification. Values are generous (64 GB for the retrains on a
  92 GB box) and should be tightened as anon-memory history accrues.
- New heavy jobs need one entry in `jobs.yaml` and `install-gates`;
  `slot` picks their start time. Agents that use `run` get all of this
  for free.
- Review after four weeks: zero Sunday failures, `gate_events` showing
  real waits with sensible durations, no interactive latency regression,
  no job skipped without a notification.

## Addendum — 2026-09-27, first busy Sunday

The first five days were all passes. The first Sunday produced three waits,
which surfaced five defects (all fixed in `coordinator/jobs.py`):

1. **Queued jobs counted as running.** A unit waiting in the gate is
   `activating`, so the poller recorded it as running with its full learned
   envelope. The AD retrain, itself queued behind the weekly retrain, held
   a phantom 52 GB and blocked the replay harvest for 51 min. Queued units
   are now their own window kind (`queued`, `[now, now + hours]`, requested
   need): they occupy nothing, and reserve against strictly lower classes,
   which is what decision 4 always said.
2. **Small work did queue behind big work.** Two 1.5 GB, 0.2-core harvests
   waited 51 and 180 min because the projected load was already over the
   line without them. A job below every `NEGLIGIBLE_*` threshold (1 GB
   VRAM, 4 GB RAM, 2 cores) now passes without a capacity check; it still
   leases and is recorded.
3. **Gate waits ate the unit's start timeout.** The wait runs inside
   `TimeoutStartSec`, so the AD harvest (8 h timeout, 6 h max wait) was
   killed mid-download after a 3 h queue. Drop-ins now set
   `TimeoutStartSec` = the unit's own + its max wait.
4. **Waits leaked into learned durations**, contrary to the consequence
   stated above (the Sunday AD retrain logged 4.2 h for 0.6 h of work).
   `profile()` now subtracts each run's gate wait (from `gate_events`), and
   a run the gate skipped contributes no footprint.
5. **A deliberate `systemctl stop` paged as a failure.** The gate returned
   the child's `-15` as exit status 241. It now dies by the child's signal,
   which systemd treats as a clean stop; a start timeout still reports
   `timeout`. A stop while queued clears the gate row and records `stopped`.

Also: wait logging fires on a change of blockers or every 10 min (a 3 h
wait had logged 240 near-identical lines), and a fixed job can be
`ack`ed to quiet its fail-streak alert until its next run.
