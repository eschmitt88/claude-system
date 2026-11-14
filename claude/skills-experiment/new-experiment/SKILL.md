---
name: new-experiment
description: /new-experiment <slug> scaffolds experiments/YYYY-MM-DD-<slug>/ (README.md, config.yaml, notes.qmd, log.md, metrics.json, results/) from the project's experiment template, copying the split spec when the project is under HCE.
respects:
  - ~/claude-system/claude/rules/evaluation.md
---

# new-experiment

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

An experiment is a dated, self-contained attempt at something measurable.
ML runs, scraping pipelines, literature batches and analysis one-shots all
use the same folder.

Create `experiments/YYYY-MM-DD-<slug>/` (today's local date, kebab-case
slug; refuse if it exists) containing:

- `README.md` from `_meta/templates/experiment.md`, with `slug`, `date` and
  `status: running` filled. Keep the template's `## Diagnostics` block
  verbatim; `/implement` and `/iterate` fill it after the run.
- `config.yaml`: a comment line and `seed: 42`.
- `notes.qmd`: a YAML header and one empty code chunk.
- `log.md`: a header only.
- `metrics.json`: `{}`, so DVC has something to track.
- `results/.gitkeep`.

**If the project is under HCE** (`evaluation.md`, "When this rule
applies"): copy `splits.yaml` from the most specific authority, which is
the task's own for a multi-task project and otherwise the project root. If
none exists yet, write a stub here (`seed`, `val_fraction`,
`test_fraction`, dataset identifiers) and say where to promote it. Never
create `final_metrics.json`. Outside HCE, skip `splits.yaml`.

Then add the folder to "Active experiments" in `_meta/index.md`, append
`YYYY-MM-DD new-experiment <slug>` to `_meta/log.md`, and commit the
scaffold by path and push. No confirmation gate.

When the experiment finishes, its `status:` and `result:` are updated and
it leaves "Active experiments".
