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

## Experiments

Every experiment is a folder at `experiments/YYYY-MM-DD-<slug>/` with:

- `README.md` — hypothesis + result, written before and updated after.
- `config.yaml` — inputs, hyperparameters, seeds.
- `notes.qmd` — running Quarto notebook (analysis, plots).
- `results/` — outputs (tracked by DVC if large).
- `log.md` — chronological log of what was run and observed.
- `metrics.json` — numeric results, tracked by DVC.

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

## What not to do

- Don't put experiment artifacts in `~/` — they go on the SN850X.
- Don't edit `raw/` after ingest — re-ingest instead.
- Don't rely on auto-memory for anything a future session must see —
  write it to a tracked file.
- Don't let project `CLAUDE.md` grow past 80 lines — split into rules.
