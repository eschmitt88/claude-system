---
name: evaluation
description: Hidden Consistent Evaluation (HCE) discipline. Applies when the active project has an evaluation holdout (a test/ directory or equivalent). Literature-only projects, scraping pipelines, and analysis one-shots can ignore this rule.
scope: experiments
---

# Evaluation discipline — Hidden Consistent Evaluation

Autonomous ML research loops fail in a recognizable way: the loop
overfits to its own evaluation signal over many cycles. AIRA2 (arXiv
2603.26499) names this as one of three dominant bottlenecks. This
rule is the mechanism that prevents it.

## When this rule applies

This rule is **opt-in by project shape**. A project is in-scope if
*any* of these are true:

- it has a `test/` directory (or symlink) under any experiment folder;
- it has a `splits.yaml` at project or experiment root;
- its CLAUDE.md declares `evaluation_mode: hce` (or equivalent).

Projects without an evaluation holdout — literature-only curation,
data scraping, analysis one-shots — can ignore this rule entirely.
`/lint` skips HCE checks on such projects.

When the rule applies, every skill that touches experiment state —
`/propose`, `/implement`, `/iterate`, `/expand`, `/ensemble`,
`/new-experiment`, and anything downstream — must obey the three
clauses below. Their frontmatter lists this file under `respects:`
as an explicit dependency declaration.

## 1. `test/` is off-limits during search

While proposing, implementing, iterating, expanding, or ensembling,
agents must not read, list, glob, or sample from the project's
`test/` directory. This includes derived forms: no `wc -l test/…`,
no `head`, no `ls test/`, no `dvc pull test/*`, no notebook cell
that touches `test/`.

The only permitted access is a **final-scoring pass**, invoked
explicitly at chain end (not inside `/iterate --chain` cycles),
whose single job is to run the held-out evaluation and write
`final_metrics.json`.

If you are about to touch `test/` during a search-phase skill, stop
and flag it to the user. `/lint` treats any `test/` access during
search as a hard failure, not a warning.

## 2. Two metric files per experiment

- `metrics.json` — **validation-split** metrics. This is the search
  signal. `/iterate` ranks on it; `/ensemble` picks members by it;
  `/lint` reads deltas from it; `/implement`'s Diagnostics section
  is grounded in it.
- `final_metrics.json` — **held-out test-split** metrics. Written
  only by the final-scoring pass. Nothing inside the search loop
  reads it.

This separation is what prevents the loop from overfitting to its
own signal across many cycles. A Diagnostics field may reference
either file but must say which (default: `metrics.json`).

## 3. Consistency across comparable experiments

Experiments that compare against each other must share the same
seeded validation split and the same test split. `splits.yaml` is
the authority; copy it, don't redefine it.

The natural scope of "comparable" depends on the project:

- **Single-task projects** (one Kaggle competition, one dataset) —
  the project root holds the authoritative `splits.yaml` and every
  experiment inherits it.
- **Multi-task projects** (e.g. a generic MLE-bench project that
  hosts many Kaggle tasks) — each task's first experiment defines
  the splits for that task; later experiments on the same task copy
  from that folder. The project root does not hold a single
  `splits.yaml` because the tasks don't share one.

Changing the split spec inside a task's scope is a **breaking
change** that invalidates cross-experiment comparisons from before
the change. Record such changes in `docs/decisions/NNNN-split-change.md`.

## Why the rule is soft-specified

The clauses above are hard. How each skill checks and enforces them
is left to the skill author — grep the tool-call log, inspect
`dvc.lock`, look at `tool_input.file_path` in hooks, or just trust
the model to honor the rule and let `/lint` catch violations after
the fact. A capable model with the rule loaded into context is the
first line of defense; the file-system and lint checks are the
backstop.
