# Personal research framework — durable principles

These principles apply to every project under `~/projects/research/`.
Project-level `CLAUDE.md` files refine them with repo-specific detail.

## Where things live

- All projects live at `~/projects/research/<slug>`. `~/projects` is a symlink
  to `/mnt/projects` (the 4 TB SN850X). Large artifacts — datasets, model
  checkpoints, HF cache, virtualenvs — belong on the SN850X under
  `~/projects/`, **never** in `~/` (the OS drive).
- `~/.claude/` on the OS drive holds only config, skills, hooks, templates.
- System binaries and Python interpreters live on the OS drive; anything a
  project produces or consumes at volume lives under `~/projects/`.

## The memory model

- **Git is the memory layer.** Every durable fact, decision, or artifact
  belongs in a tracked file. Auto-memory is a hint, not a home — promote
  anything load-bearing into a file in the project.
- Plain **Markdown** with flat **YAML frontmatter**. No proprietary formats,
  no nested schemas. Easy to grep, easy to diff, easy to migrate.
- `raw/` is **immutable**: snapshots of papers, repo clones, web captures.
  The agent reads it; nothing writes to it after ingest.
- Processed understanding lives in `literature/`, `concepts/`, `mocs/`,
  `experiments/`. Each has a template in `_meta/templates/`.

## Git autonomy — commit and push without asking

This applies to **every** git repo I work in, not just `~/projects/research/`
ones, and it **overrides** the Claude Code harness default ("commit or push
only when the user asks; branch first on the default branch").

- **Commit and push automatically** at logical checkpoints — a finished fix,
  a scheduled-job change, a batch of run records. Don't wait for permission
  and don't leave committed-but-unpushed work; the remote/Pages tree is the
  live source of truth.
- **Commit directly on the working branch** (e.g. `master`/`main`). Do *not*
  spin up a feature branch just because it's the default branch — match the
  repo's established pattern, which here is direct commits.
- Keep commits logically scoped with clear messages; respect `.gitignore` and
  the DVC/SN850X boundary (never commit large artifacts — `model.pt`,
  parquet, datasets — into git).
- **Stage by path**, not `git add -A` / `commit -a`: scheduled jobs and
  other sessions leave these repos dirty, and a sweep commits their
  half-written state under your message.
- Judgment still applies: don't commit secrets, half-broken WIP that doesn't
  build, or someone else's uncommitted state swept in by accident. When a
  change is genuinely risky or ambiguous, flag it instead of committing.

## Experiments

Every experiment is a folder at `experiments/YYYY-MM-DD-<slug>/`, scaffolded
by `/new-experiment`: hypothesis and result in `README.md`, inputs and seeds
in `config.yaml`, analysis in `notes.qmd`, a chronological `log.md`, numbers
in `metrics.json`, outputs under `results/`.

DVC tracks data and model artifacts. Git tracks code, configs, and notes.

## End-of-task discipline

- Every work session ends with a `NOTES.md` update: **Did / Findings / Next**.
  This is enforced by the `/wrap` skill and a `SessionEnd` hook — not by
  asking nicely.
- Decisions that affect future work go in `docs/decisions/NNNN-<slug>.md`
  (lightweight ADR).
- Daily session files land under `journal/YYYY-MM-DD.md` (written by the
  SessionEnd hook).

## Project CLAUDE.md rules

- Project-root `CLAUDE.md` stays **under 80 lines**.
- Use `@imports` and path-scoped `.claude/rules/` for detail. Example:
  `.claude/rules/experiments.md` applies only when touching
  `experiments/**`.
- The root file should orient, not explain. Long explanations belong in
  scoped rules or in `_meta/` docs.

## Framework rules (research projects only)

The HCE evaluation discipline and the agency (autonomous-spend) levels
live at `~/claude-system/claude/rules/{evaluation,agency}.md`. They are
not loaded globally (they would cost context in every repo), so they are
read on demand: every skill that lists them under `respects:` Reads them
first, and outside a skill, read `evaluation.md` before designing or
judging an evaluation and `agency.md` before an autonomous run.

## Knowledge graph hygiene

- When ≥5 related concepts accumulate on a theme, promote them to a
  **Map of Content** (`mocs/<theme>.md`).
- `/lint` runs weekly to surface orphans: literature notes with no
  `related_experiments`, high-relevance papers with no follow-up, dead
  wikilinks, concepts with no `sources:`.

## Runtime discipline

- **Destructive runs happen in Git worktrees.** Never run mutating
  experiments against the primary checkout.
- **Subagents handle high-volume narrow work** — literature review, log
  parsing, corpus sweeps. The main agent owns primary context and
  decisions.
- Worktrees go under `~/projects/research/<slug>/.worktrees/`, not
  alongside the main checkout.

## Writing instructions for another model

This covers subagent briefs, skills, rules, hook text and scheduled-job
prompts. The reader is as capable as you and knows nothing you haven't
written down. The evidence behind each line, and the rest of the guide, is
at `~/projects/research/intent-briefing/docs/writing-guide.md`; read it
before writing or rewriting a skill.

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

The machine runs a fleet of timer-driven jobs (retrains, harvests,
monitors) with learned GPU/RAM/CPU footprints. Every session starts with
a "Box schedule" notice; `/headroom` repeats it.

- **Before a GPU or multi-core run longer than ~15 min**, ask for a
  window: `claude-coordinator-jobs window --gpu-gb G --ram-gb R --hours H`
  (binary in `~/claude-system/coordinator/.venv/bin/`). Start when it
  fits, or at `earliest_fit`; don't launch into a predicted collision.
- **Launch runs longer than ~30 min attributed**:
  `claude-coordinator-jobs run --name <slug> --gpu-gb G --hours H --log <file> -- <cmd>`.
  It goes through the capacity gate (class `agent`: waits for production
  retrains, passes when it fits), other sessions see it, and its
  footprint is learned. `--no-gate` bypasses; `queue` shows waits.
- **Adding a new timer/cron job?** `claude-coordinator-jobs slot --hours H [--gpu-gb G]`
  picks the daily start with the least overlap.
- `/jobs` has the inventory, forecast, per-job profiles and health.
- **Fixed a failing scheduled job?** `claude-coordinator-jobs ack <unit>` —
  silences the fail-streak alert until its next run (which re-alerts if it fails).

## Monitoring long-running ML jobs (>30 min)

Multi-hour training/build jobs are not fire-and-forget. The LLM can
detect off-the-rails runs faster than a human — use it.

- **Launch with `python -u`** so stdout isn't block-buffered (default
  `nohup`-redirected Python buffers ~8 KB → silent training looks like
  a hang).
- **Poll the log every 10-30 min.** Tail, check metric trajectory,
  check process state (CPU/GPU util, RSS), scan `journalctl` for
  kernel events.
- **Halt on a PATTERN of 3+ consecutive bad epochs**, not a single
  reading. Bad signals: train loss increasing (anti-learning), val
  metric stuck at random baseline, NaN/Inf, multi-task weights
  collapsing to single-task-dominant, GPU 0% util + CPU 100% sustained,
  kernel events (OOM/RCU/MCE).
- **Document the kill** in the experiment's `log.md` AND project
  `_meta/log.md`: what signal triggered, what the log showed.

## Tools of record

- `git` for code and prose.
- `dvc` for data, model, and large-result tracking.
- `uv` for Python environments (`.venv/` is gitignored).
- `quarto` for `.qmd` notebooks.
