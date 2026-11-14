---
name: evaluation
description: Hidden Consistent Evaluation (HCE) discipline. Applies when the active project has an evaluation holdout (a test/ directory or equivalent). Literature-only projects, scraping pipelines, and analysis one-shots can ignore this rule.
scope: experiments
---

# Evaluation discipline — Hidden Consistent Evaluation

An autonomous research loop overfits to its own evaluation signal over
many cycles (AIRA2, arXiv 2603.26499, names it one of three dominant
bottlenecks). These four clauses are what prevents it.

## When this rule applies

A project is in scope if any of these is true:

- it has a `test/` directory (or symlink) under any experiment folder;
- it has a `splits.yaml` at project or experiment root;
- its `CLAUDE.md` declares `evaluation_mode: hce`.

Projects with no holdout can ignore the rule, and `/lint` skips its checks
there. Where it applies, every skill that touches experiment state obeys
all four clauses.

## 1. `test/` is off-limits during search

While proposing, implementing, iterating, expanding or ensembling, do not
read, list, glob or sample the project's `test/` directory, in any form:
no `wc -l test/…`, no `head`, no `ls test/`, no `dvc pull test/*`, no
notebook cell that touches it.

**The boundary includes retrieval.** During search, do not web-search or
fetch the task's own benchmark artifacts: its leaderboard, published
solutions or write-ups, the dataset's hosting or discussion pages, or the
withheld source method of a discovery-style task. Content carrying
held-out labels or a published solution is holdout access by another
route: the score stops measuring search and starts measuring lookup.
Technique-level retrieval (API docs, library usage, general methods) is
fine. The test is whether the query names the task or benchmark rather
than the technique. If task-specific artifacts surface unexpectedly,
record it in `log.md` and report it with the metrics.

The only permitted access is a **final-scoring pass**: invoked explicitly
at chain end (never inside `/iterate --chain`), with the single job of
running the held-out evaluation and writing `final_metrics.json`. It runs
**once per chain**. Never re-run it after further changes "to
double-check", and never because the first number disappointed: a repeated
final pass is search-phase access.

If you are about to touch `test/` during search, stop and flag it. `/lint`
treats it as a hard failure.

## 2. Two metric files per experiment

- `metrics.json`: **validation-split** metrics, the search signal.
  `/iterate` ranks and picks ensemble members by it, `/lint` reads deltas
  from it, and Diagnostics are grounded in it.
- `final_metrics.json`: **held-out test-split** metrics, written only by
  the final-scoring pass. Nothing in the search loop reads it.

A test score, once read, is **spent**. Whoever plans the next chain has
seen it, so a later chain on the same task is partly selected on the
holdout and its own final score is no longer unbiased. Keep final passes
rare. When a task has had several across chains, say so wherever the
held-out number is reported: it is exploratory by then, not confirmatory.

A Diagnostics field may cite either file but must say which (default
`metrics.json`).

## 3. Consistency across comparable experiments

Experiments that are compared share the same seeded validation split and
the same test split. `splits.yaml` is the authority: copy it, don't
redefine it.

- **Single-task projects**: the project root holds `splits.yaml` and every
  experiment inherits it.
- **Multi-task projects**: each task's first experiment defines that
  task's splits, and later experiments on the task copy from it.

Changing the split spec within a task is a **breaking change** that
invalidates earlier comparisons. Record it in
`docs/decisions/NNNN-split-change.md`.

## 4. The evaluator is part of the holdout

Split hygiene does not protect the metric itself: an agent that edits the
code computing the score can raise the number without touching `test/`.

- At chain start, record the content hash of the evaluator (the script or
  function that computes `metrics.json` / `final_metrics.json`) in the
  experiment's `log.md`.
- Also at chain start, score a do-nothing submission with the search
  evaluator and log the score beside the hash: the task's sample
  submission, a constant or majority-class prediction, or an empty output.
  It should land at the task's floor (chance AUC, the majority-class rate,
  the empty-output score). If it lands clearly above, the evaluator is
  reading something other than the submission; fix it before the chain
  starts. A hash proves the evaluator is unchanged, not that it is right,
  and a passing check only rules out rewarding nothing. Where a task has
  no defined floor, skip with a logged reason.
- The final-scoring pass runs a **pristine copy** of the evaluator, from
  the chain-start commit (`git show <sha>:<path>`) or a read-only location
  outside the loop's writable tree, never the workspace copy, and writes
  the hash it ran into `final_metrics.json`.
- A workspace evaluator that no longer matches the recorded hash is a
  finding to report, not something to re-hash quietly. A deliberate metric
  change is a breaking change, recorded like a split change.

## Enforcement

The clauses are hard. A model with this rule in context is the first line
of defence; `/lint`'s scan of logs and `dvc.yaml` is the backstop.
