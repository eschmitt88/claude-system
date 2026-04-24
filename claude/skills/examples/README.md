# skills/examples/

Reference skills that are **not** installed as first-class slash commands.
They exist as worked examples of how to extend the framework for a
specific benchmark or external system.

Copy them into `claude/skills/` (and restart Claude Code) if you want
them live.

## Current examples

- **`mle-task/`** — Scaffolds a Kaggle competition from a local
  [MLE-bench](https://github.com/openai/mle-bench) clone into the
  standard experiment layout (dated folder, `train/` + `test/`
  symlinks, seed proposal, task-specific `CLAUDE.md`). Used once for
  the Phase 5 capability smoke test.

- **`mle-score/`** — Final-scoring pass for an MLE-bench experiment.
  The only skill allowed to read from `test/` per HCE rule. Invokes
  `mlebench grade-sample` and writes `final_metrics.json`.

## Why they're not installed

The framework should not assume every project is an ML experiment
against an external grader. MLE-bench is one kind of task — useful,
but narrow. Projects that don't have a train/test split (literature
reviews, scraping pipelines, analysis one-shots) shouldn't see these
skills cluttering their `/help`.

If you find yourself running MLE-bench repeatedly, copy these back
into `claude/skills/` and commit.
