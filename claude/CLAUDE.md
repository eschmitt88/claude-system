# Personal research framework — durable principles

These apply to every project under `~/projects/research/`. Project-level
`CLAUDE.md` files refine them.

## Where things live

- Projects live at `~/projects/research/<slug>`. `~/projects` is a symlink
  to `/mnt/projects` (the 4 TB SN850X).
- Anything a project produces or consumes at volume (datasets, checkpoints,
  HF cache, virtualenvs) goes under `~/projects/`, **never** in `~/` (the OS
  drive). `~/.claude/` holds only config, skills, hooks and templates.

## The memory model

- **Git is the memory layer.** Every durable fact, decision or artifact
  belongs in a tracked file. Auto-memory is a hint, not a home.
- Plain **Markdown** with flat **YAML frontmatter**: no proprietary formats,
  no nested schemas.
- `raw/` is **immutable**: source snapshots. Nothing writes to it after
  ingest; re-ingest instead.
- Processed understanding lives in `literature/`, `concepts/`, `mocs/` and
  `experiments/`, each from a template in `_meta/templates/`. When ≥5
  related concepts accumulate on a theme, promote them to
  `mocs/<theme>.md`.
- Tools of record: `git` for code and prose, `dvc` for data, models and
  large results, `uv` for Python environments, `quarto` for `.qmd`
  notebooks.

## Git autonomy — commit and push without asking

This applies to **every** git repo I work in, and it **overrides** the
Claude Code harness default ("commit or push only when the user asks;
branch first on the default branch").

- **Commit and push automatically** at logical checkpoints. Don't wait for
  permission, and don't leave committed-but-unpushed work: the remote and
  its Pages tree are the live source of truth.
- **Commit directly on the working branch** (`master`/`main`). No feature
  branch just because it's the default branch; match the repo's pattern.
- **Stage by path**, not `git add -A` / `commit -a`: scheduled jobs and
  other sessions leave these repos dirty, and a sweep commits their
  half-written state under your message.
- Keep commits scoped, with clear messages. Never commit large artifacts
  (`model.pt`, parquet, datasets), secrets, or WIP that doesn't build. When
  a change is risky or ambiguous, flag it instead of committing.

## Sessions and experiments

- Every work session ends with a `NOTES.md` update, **Did / Findings /
  Next**, via `/wrap`. The SessionEnd hook backstops it and writes
  `journal/YYYY-MM-DD.md`.
- Decisions that affect future work go in `docs/decisions/NNNN-<slug>.md`.
- An experiment is a folder `experiments/YYYY-MM-DD-<slug>/`, scaffolded by
  `/new-experiment` (README, `config.yaml`, `notes.qmd`, `log.md`,
  `metrics.json`, `results/`).
- **Destructive runs happen in Git worktrees** under
  `~/projects/research/<slug>/.worktrees/`, never in the primary checkout.
- **Subagents handle high-volume narrow work** (literature review, log
  parsing, corpus sweeps). The main agent owns primary context and
  decisions.

## Project CLAUDE.md and rules

- A project-root `CLAUDE.md` stays **under 80 lines** and orients, not
  explains. Detail goes in `.claude/rules/*.md`, each scoped with `paths:`
  frontmatter so it loads only when a matching file is touched.
- The framework rules, HCE evaluation and agency levels, live at
  `~/claude-system/claude/rules/{evaluation,agency}.md` and load only on
  demand. Skills that list them under `respects:` read them first. Outside
  a skill, read `evaluation.md` before designing or judging an evaluation
  and `agency.md` before an autonomous run.

## Writing instructions for another model

This covers subagent briefs, skills, rules, hook text and scheduled-job
prompts. The reader is as capable as you and knows nothing you haven't
written down. The evidence, and the rest of the guide, is at
`~/projects/research/intent-briefing/docs/writing-guide.md`; read it before
writing or rewriting a skill.

- **State what the reader won't do by default**: conditional requirements,
  the shape of what to send back, scope limits, what you already ruled
  out. Leave out what it would do anyway.
- **Give the outcome, when to stop, and constraints with their reasons.**
  Spell out steps only where the order is itself the requirement.
- **A rule that must hold goes in code** (a hook, a script, a typed check),
  not in prose of any style.
- **A cheaper reader gets more structure.** Brief a Sonnet or Haiku subagent
  more explicitly than you would a peer.

## Shared box — plan compute around scheduled jobs

The machine runs timer-driven jobs (retrains, harvests, monitors) with
learned footprints. Every session starts with a "Box schedule" notice.
`J=~/claude-system/coordinator/.venv/bin/claude-coordinator-jobs`; `/jobs`
has the detail.

- **Before a GPU or multi-core run longer than ~15 min**, ask for a window:
  `$J window --gpu-gb G --ram-gb R --hours H`. Start when it fits or at
  `earliest_fit`; don't launch into a predicted collision.
- **Launch runs longer than ~30 min attributed**:
  `$J run --name <slug> --gpu-gb G --hours H --log <file> -- <cmd>`. It
  waits behind production retrains, other sessions can see it, and its
  footprint is learned.
- **New timer or cron job**: `$J slot --hours H [--gpu-gb G]` picks the
  daily start with the least overlap.
- **Fixed a failing scheduled job**: `$J ack <unit>` silences its
  fail-streak alert until the next run.

## Monitoring long-running ML jobs (>30 min)

Multi-hour training and build jobs are not fire-and-forget.

- **Launch with `python -u`**: redirected Python block-buffers stdout, so
  silent training looks like a hang.
- **Poll the log every 10–30 min**: metric trajectory, process state
  (CPU/GPU util, RSS), `journalctl` for kernel events.
- **Halt on a pattern of 3+ consecutive bad epochs**, not one reading:
  train loss rising, val metric stuck at the random baseline, NaN/Inf,
  multi-task weights collapsing to one task, GPU 0% with CPU 100%
  sustained, kernel events (OOM/RCU/MCE).
- **Document the kill** in the experiment's `log.md` and the project's
  `_meta/log.md`: what signal triggered it and what the log showed.
