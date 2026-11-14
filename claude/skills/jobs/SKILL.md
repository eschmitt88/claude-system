---
name: jobs
description: Schedule-aware headroom. Shows the recurring jobs on this box, what each costs (learned GPU/RAM/CPU/duration), a forecast, and the earliest window a proposed run fits; launches long runs as attributed, gated units. Use before any GPU or multi-core run longer than a few minutes.
---

# jobs

The box is shared with a fleet of scheduled jobs. Before spending GPU or
CPU for more than a few minutes, see what is about to run and plan around
it. Nothing has to be registered: the ledger is derived from systemd
timers, the crontab, cgroup accounting and the journal.

```bash
J=~/claude-system/coordinator/.venv/bin/claude-coordinator-jobs
$J window --gpu-gb 8 --ram-gb 20 --cores 4 --hours 2   # earliest slot that fits
$J run --name <slug> --gpu-gb 8 --ram-gb 16 --hours 2 --log <path>.log -- python -u train.py
$J forecast --hours 24        # predicted busy windows
$J now                        # running jobs and who holds GPU memory
$J slot --gpu-gb 6 --hours 1  # best daily start for a NEW scheduled job
$J health                     # jobs failing repeatedly
$J ack UNIT                   # you fixed one: no alerts until its next run
$J queue                      # gate: waiting jobs, leases, recent decisions
```

`$J --help` lists the rest (`list`, `profile`, `runs`, `sync`, `brief`,
the gate installers). `--json` goes before the subcommand.

## What the output means

- **`window`** checks VRAM (1 GB margin), RAM (8 GB margin) and cores (90%
  of the box) against the peak overlap inside your span. `earliest_fit` is
  the first start that passes; `least_bad` is the fallback when nothing
  does. It is advisory: a scheduled job does not know about a run you
  started by hand, and will start on top of it.
- **`run`** puts the command in a transient user unit, so it is
  cgroup-attributed, visible to every other session, and its footprint is
  learned. It passes the capacity gate as class `agent`: it waits behind
  production work and starts at once when it fits (`--no-gate` bypasses,
  `--class` raises). With `--log` it detaches and returns; follow with
  `tail -f` or `journalctl --user -u <unit> -f`. A failure pushes a
  notification.
- **Footprints** are p90 over recent successful runs. Forecast windows run
  from `start ± RandomizedDelaySec` to `start + delay + p90 duration`,
  conservative on purpose. `light` jobs are hidden from timelines.

## The capacity gate

Heavy timer jobs are wrapped by the gate through systemd drop-ins
generated from `~/.claude/jobs.yaml` (`$J install-gates` after editing it;
example in `~/claude-system/registry/jobs.example.yaml`). A gated job
starts only when its envelope fits beside running leases and
higher-priority jobs about to start; otherwise it waits up to its
`max_wait`, then runs or skips per policy. Classes are `production` >
`batch` > `agent`, first-come within a class. Design:
`~/claude-system/docs/decisions/0002-capacity-gate.md`.
