---
name: jobs
description: Schedule-aware headroom. /jobs shows what recurring jobs run on this box (systemd timers + crontab), what each costs (GPU VRAM, RAM, CPU, duration — learned passively from cgroup + journal telemetry), a forecast of the next 24-48h, and the earliest window where a proposed run fits. Also launches long runs as attributed transient units. Read-only except `run`. Wraps ~/claude-system/coordinator/.venv/bin/claude-coordinator-jobs.
---

# jobs

The box is shared with a fleet of scheduled jobs (nightly retrains, data
harvests, monitors). Before spending GPU/CPU for more than a few minutes,
look at what is about to run and plan around it. Nothing needs to be
registered — the ledger is derived from systemd timers, the user crontab,
cgroup v2 accounting and the journal.

## Commands

```bash
J=~/claude-system/coordinator/.venv/bin/claude-coordinator-jobs
$J brief                      # 6-line notice (what session-start injects)
$J now                        # running tracked jobs + who holds GPU memory
$J forecast --hours 24        # predicted busy windows, running first
$J window --gpu-gb 8 --ram-gb 20 --cores 4 --hours 2   # earliest slot that fits
$J list                       # inventory + learned footprints + fail streaks
$J profile <unit>             # one job: duration p90, VRAM/RAM p90, cores, reliability
$J runs [<unit>] -n 20        # recent observed runs
$J slot --gpu-gb 6 --hours 1  # best recurring daily start for a NEW scheduled job
$J health                     # jobs failing repeatedly (exit 1 if any)
$J sync --backfill 14         # refresh inventory, re-read 14d of journal
```

Add `--json` before the subcommand for structured output.

## Launch long runs attributed

```bash
$J run --name <slug> --gpu-gb 8 --ram-gb 16 --hours 2 --log <path>.log -- python -u train.py
```

Runs the command in a transient user unit (`job-<slug>-<mmddHHMM>`), so
it is cgroup-attributed, appears in `now`/`forecast` for every other
session, and its footprint feeds future profiles. With `--log` it detaches
and returns immediately (`journalctl --user -u <unit> -f` or `tail -f`
to follow); without, it blocks with stdio piped. Prints an advisory note
if starting now conflicts with the forecast — it never blocks the launch.

## Reading the output

- **Footprints** are p90 over the newest successful runs: VRAM is exact
  (NVML per-process, mapped to units via `/proc/<pid>/cgroup`); RSS is
  `memory.peak`; cores = CPU-seconds / wall time. Runs only seen in the
  journal (before the poller tracked them) carry box-level deltas instead
  (`ΔRAM`, `est_vram`), measured on the "clean prefix" of the run — up to
  the first other job that starts inside it. Once a job has live-attributed
  runs, only those define RAM/VRAM; the deltas are a day-one bootstrap.
- **Classes**: `gpu` / `cpu` / `ram` (joined with `+`) matter for planning;
  `light` (bursts, negligible jobs) is hidden from timelines; `long-light`
  (negligible footprint, long wall time) is shown as context only.
- **Windows** are `start ± RandomizedDelaySec` to `start + delay + p90
  duration`. Conservative on purpose.
- `window` checks VRAM (1 GB margin), RAM (8 GB margin) and cores (90 %
  of the box) against the peak overlap inside your span. `earliest_fit`
  is the first candidate start (now, or the end of some forecast window)
  that passes; `least_bad` is the fallback when nothing does.
- **Advisory, not a gate.** If you start a GPU run anyway, expect the
  scheduled job to still run — it does not know about you unless you
  launched via `run`.

## Optional annotations

`~/.claude/jobs.yaml` (untracked; example in
`~/claude-system/registry/jobs.example.yaml`) can attach `project`,
`notes`, `ignore: true`, or an `expect:` envelope for a job with no
history yet.
