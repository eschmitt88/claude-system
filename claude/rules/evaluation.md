---
name: evaluation
description: Hidden Consistent Evaluation (HCE) discipline. Authoritative rule referenced by every skill that proposes, implements, iterates, expands, ensembles, or scaffolds experiments.
scope: experiments
---

# Evaluation discipline — Hidden Consistent Evaluation

Autonomous ML research loops fail in a recognizable way: the loop overfits
to its own evaluation signal over many cycles. AIRA2 (arXiv 2603.26499)
names this as one of three dominant bottlenecks. This rule is the mechanism
that prevents it.

Every skill that touches experiment state — `/propose`, `/implement`,
`/iterate`, `/expand`, `/ensemble`, `/new-experiment`, and anything down-
stream — must obey the three clauses below. Their frontmatter lists this
file under `respects:` as an explicit dependency declaration.

## 1. `test/` is off-limits during search

While proposing, implementing, iterating, expanding, or ensembling, agents
must not read, list, glob, or sample from the project's `test/` directory.
This includes derived forms: no `wc -l test/…`, no `head`, no `ls test/`,
no `dvc pull test/*`, no notebook cell that touches `test/`.

The only permitted access is a **final-scoring pass**, invoked explicitly
at chain end (not inside `/iterate --chain` cycles), whose single job is
to run the held-out evaluation and write `final_metrics.json`.

If you are about to touch `test/` during a search-phase skill, stop and
flag it to the user. `/lint` treats any `test/` access during search as
a hard failure, not a warning.

## 2. Two metric files per experiment

- `metrics.json` — **validation-split** metrics. This is the search signal.
  `/iterate` ranks on it; `/ensemble` picks members by it; `/lint` reads
  deltas from it; `/implement`'s Diagnostics section is grounded in it.
- `final_metrics.json` — **held-out test-split** metrics. Written only by
  the final-scoring pass. Nothing inside the search loop reads it.

This separation is what prevents the loop from overfitting to its own
signal across many cycles. A Diagnostics field may reference either file
but must say which (default: `metrics.json`).

## 3. Consistency across experiments in a project

All experiments in a project share the same seeded validation split and
the same test split. `/new-experiment` copies the split spec from the
project root (`splits.yaml` if present; otherwise emits a stub and tells
the user to fill it).

Changing the split spec is a **project-level decision**, not an
experiment-level one — treat it as a breaking change that invalidates
cross-experiment comparisons from before the change. Record such changes
in `docs/decisions/NNNN-split-change.md`.

## Why the rule is soft-specified

The clauses above are hard. How each skill checks and enforces them is
left to the skill author — grep the tool-call log, inspect `dvc.lock`,
look at `tool_input.file_path` in hooks, or just trust the model to
honor the rule and let `/lint` catch violations after the fact. A
capable model with the rule loaded into context is the first line of
defense; the file-system and lint checks are the backstop.
