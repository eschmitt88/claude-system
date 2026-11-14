# Agency — how much a project's agents do unasked

Set per repo by `agency:` in `budget.yaml`.

- **`standard`** (the default, and what a missing field means): propose and
  wait. Candidates are left for the user to curate, `/iterate` pauses each
  cycle, and nothing fetches, ingests or launches experiments without a
  go-ahead.
- **`max`**: act. Fetch, ingest, curate, propose and iterate without
  pausing, while the coordinator's verdict permits and the `budget.yaml`
  ceilings hold. The point is to use headroom: weekly quota left unspent
  at the reset is wasted.

## Confirmation principle

One rule decides which skills pause for a human:

> **Artifact writes** — ingesting sources, literature/concept notes,
> scaffolds, logs, wrap entries — commit autonomously everywhere, in
> every repo. **Hypothesis selection** — proposals, expansion children,
> ensemble choices, MoC promotion, derived experiments — confirms under
> `agency: standard` and auto-advances under `agency: max` (verdict
> permitting).

Recording what happened needs no approval, because git makes it
reversible. Choosing what to spend compute on is the decision worth a human
look, and only in repos that haven't opted into autonomy. Over-gating has a
measured cost (wu2026hasbench: +50% interaction turns for diminishing or
negative returns).

## The headroom gate

In a `max` repo, ask before a burst of autonomous work, and again every
few units inside one, because quota and GPU state move:

```sh
~/claude-system/coordinator/.venv/bin/claude-coordinator-agency --json
```

It returns `verdict` (`go`, `slow`, `hold`) and `aggressiveness` (`high`,
`normal`, `low`, `none`), from reset-anchored token pacing (how far the
weekly quota is spent against a pace that would use it exactly at reset)
and live CPU/RAM/GPU and disk headroom. `suggested_session_tokens` is the
advisory budget.

| aggressiveness | batch |
|---|---|
| `high` | about 6 fetch→ingest items per burst; chain `/iterate` cycles |
| `normal` | about 3; one `/iterate` cycle, re-check between units |
| `low` | about 2, one at a time |
| `hold` verdict | start nothing new, even mid-burst. Log why and stop; the next scheduled run resumes |

This table is the canonical batch scale; skills refer to it.

What `max` turns on, with the steps owned by each skill: `/digest` ingests
its top candidates; `/curate` drains the standing backlog (a candidate file
with no disposition is unfinished work); `/iterate` chains when the GPU is
free (`hardware.gpu_free`); `/promote-moc` runs after an ingest burst and
keeps its restraint (no thin MoCs because agency is `max`).

GPU or multi-core runs follow the "Shared box" section of
`~/.claude/CLAUDE.md`: ask for a window, launch attributed.

## Persist the work

The per-repo Pages site reads the live GitHub tree, so autonomous work is
invisible until pushed. Commit and push at each natural boundary (each
ingested paper, each curated file), not once at the end. The SessionEnd
auto-push is a backstop.

Stage by path: commit the files the work wrote, never `git add -A` or
`commit -a`. Scheduled jobs and other sessions keep these repos dirty, and
a sweep commits their half-written state under your message.

## Hard limits under `max`

- **`budget.yaml` ceilings are absolute**: `max_tokens`, `max_wall_hours`,
  `max_experiments`, `max_consecutive_no_improvement`, `max_disk_gb`.
  `scripts/chain_budget.py` evaluates them for `/iterate` chains. Nothing
  meters an ingest or curate burst against them, so there the verdict and
  the batch scale are the limit.
- **HCE still applies** (`evaluation.md`). `max` never licenses touching
  the holdout.
- **`hold` is absolute.**
