# Agency — autonomous-spend levels per project

How much initiative an agent should take in a project is a per-repo
setting, declared in `budget.yaml` as `agency:`. Two levels:

- **`standard`** (default) — propose and wait. Discovery drops candidates
  for the user to curate; `/iterate` pauses each cycle; nothing fetches,
  ingests, or launches experiments without a human go-ahead. This is the
  safe default; a repo with no `agency:` field is `standard`.
- **`max`** — act autonomously. In a `max` repo the agent should *make
  use of headroom*: fetch papers, ingest them, propose, and iterate
  without pausing for confirmation, **while the coordinator's agency
  verdict permits and the `budget.yaml` ceilings hold.**

This rule applies to the discovery/execution skills — `/digest`,
`/discover`, `/fetch-paper`, `/ingest`, `/propose`, `/iterate`. They list
this file under `respects:`.

## The headroom gate

Before a burst of autonomous work in a `max` repo, consult the verdict:

```sh
~/claude-system/coordinator/.venv/bin/claude-coordinator-agency --json
```

It returns `verdict` ∈ {`go`, `slow`, `hold`} and `aggressiveness` ∈
{`high`, `normal`, `low`, `none`}, computed from:

- **Reset-anchored token pacing** — how far the weekly quota is spent vs a
  steady pace that would consume it exactly at reset. Being *behind* pace
  (especially as the reset nears) means slack to spend now; unused weekly
  quota is wasted. `suggested_session_tokens` is the advisory slack budget.
- **Live hardware headroom** — CPU/RAM/GPU utilization and free disk.
  Below ~50% utilization there is room to run more concurrently.

Act on it:

- **`go` / high** — proceed aggressively. Fetch + ingest the top
  candidates in the queue; chain `/iterate` cycles; batch the work.
- **`go` / `slow` (normal/low)** — proceed, but smaller batches; one
  fetch→ingest at a time, single `/iterate` cycle, re-check the verdict
  between units.
- **`hold`** — do not start new autonomous work. Log why and stop. Resume
  on the next scheduled run when headroom recovers.

Re-check the verdict periodically inside a long autonomous burst (e.g.
every few units of work), not just once — quota and GPU state move.

## What `max` changes, skill by skill

- **`/digest`** — after writing candidates, if `agency: max` and the
  verdict is not `hold`, **auto-advance the backlog**: `/fetch-paper` +
  `/ingest` the highest-ranked candidates (count scaled by
  aggressiveness — e.g. up to ~6 on `high`, ~2 on `low`), instead of
  leaving them for manual curation. This is the deliberate relaxation of
  `/digest`'s "never auto-ingest" default, scoped to opt-in repos.
- **`/discover` / `/fetch-paper` / `/ingest`** — already commit without a
  confirmation gate; under `max` they may also be chained automatically by
  `/digest` rather than user-invoked one at a time.
- **`/iterate`** — under `max` and a non-`hold` verdict with the GPU free
  (`hardware.gpu_free`), run as `--chain` within the `budget.yaml`
  ceilings instead of pausing per cycle.
- **`/promote-moc`** — after an ingest burst adds or links concepts, run
  `/promote-moc` (auto-detect) so a newly-ripe cluster becomes a Map of
  Content without waiting to be asked. It promotes only genuinely ripe,
  un-mapped clusters (>=5 related concepts not already in a MoC) and
  declines redundant ones — keep that restraint; do not manufacture thin
  MoCs just because agency is `max`.
- **`/curate`** — don't let candidate files pile up. Drain the standing
  `raw/_candidates/` backlog: ingest the keepers, decline the rest with a
  recorded reason, and archive each file to `raw/_candidates/_done/`. A
  candidate file with no disposition is unfinished work; `max` repos close
  it rather than leaving an "uncurated" pile.

## Persist the work — push at the end of every autonomous burst

The per-repo Pages site reads the **live** GitHub tree, so autonomous work
is invisible until it is pushed. After any autonomous burst in a `max`
repo — a `/digest` auto-advance, a chained `/iterate`, a batch of
`/ingest`s — **commit and `git push`** so the changes land on GitHub and
the Pages site updates. Never leave committed-but-unpushed work at the end
of an autonomous run; the SessionEnd auto-push is a backstop, not the
primary mechanism. Push at each natural boundary (e.g. after each ingested
paper), not only once at the very end, so progress is visible as it lands.

## Hard limits that still bind under `max`

Autonomy is bounded, not unbounded:

- **`budget.yaml` ceilings are absolute** — `max_tokens`, `max_wall_hours`,
  `max_experiments`, `max_consecutive_no_improvement`, `max_disk_gb`. Halt
  when any is hit, regardless of verdict.
- **HCE still applies** — `test/` stays off-limits during search; see
  `evaluation.md`. `max` agency never licenses touching the holdout.
- **`hold` is absolute** — a `hold` verdict (weekly quota ≥90% spent, disk
  critically low) stops new autonomous work even mid-burst.
- **Destructive/expensive jobs still declare to the coordinator** via
  `/plan` so the queue and PreToolUse cap can see them.
