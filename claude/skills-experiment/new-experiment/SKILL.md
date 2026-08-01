---
name: new-experiment
description: Scaffold an experiment folder at experiments/YYYY-MM-DD-<slug>/ with README.md, notes.qmd, config.yaml, results/, log.md, metrics.json. Pre-fills frontmatter from _meta/templates/experiment.md. If the project opts into HCE (has a splits.yaml or test/ directory), also copies the split spec — otherwise splits.yaml is skipped.
respects:
  - ~/claude-system/claude/rules/evaluation.md
---

# new-experiment

Create a new experiment folder in the active project.

An **experiment** is a dated, self-contained attempt at something
measurable — that's the only invariant. ML runs, scraping pipelines,
literature-review batches, and analysis one-shots all share the same
folder convention.

## Arguments

- `<slug>` — kebab-case name for the experiment. Required.

## Steps

1. **Compute the folder name**: `experiments/YYYY-MM-DD-<slug>/` using
   today's local date. Refuse if that folder already exists.

2. **Create the folder and files**:

   - `README.md` — seeded from `_meta/templates/experiment.md`, with
     frontmatter `slug`, `date`, `status: running` pre-filled. The
     template ships with a `## Diagnostics` fill-in-the-blank section
     (canonical field list: `/implement` step 5). Preserve the
     template verbatim so `/implement` and `/iterate` can fill it
     after the run.
   - `config.yaml` — minimal stub:
     ```yaml
     # Inputs, hyperparameters, seeds for this experiment.
     seed: 42
     ```
   - `notes.qmd` — Quarto stub with a YAML header and one empty code
     chunk.
   - `results/.gitkeep` — empty placeholder.
   - `log.md` — header only.
   - `metrics.json` — `{}` so DVC has something to track.

3. **HCE mode (optional).** Check whether this project opts into the
   HCE rule (triggers: `~/claude-system/claude/rules/evaluation.md`, "When this
   rule applies").

   **If opted-in:**
   - Copy `splits.yaml` from the most specific authority available:
     the parent task's splits.yaml if one exists (for multi-task
     projects), otherwise the project root.
   - If no authoritative splits.yaml exists yet, emit a stub inside
     this experiment:
     ```yaml
     # Shared data splits for this scope. Promote to the authoritative
     # location (task root or project root) when ready.
     seed: 42
     val_fraction: 0.1
     test_fraction: 0.1
     # dataset-specific identifiers go here
     ```
     and tell the user where to promote it.
   - **Do not** create `final_metrics.json` here — final-pass only,
     per `~/claude-system/claude/rules/evaluation.md` clause 2.

   **If not opted-in:** skip `splits.yaml` entirely. The experiment
   has no held-out evaluation. `metrics.json` is still the canonical
   metric file — it just has no "val vs test" semantics.

4. **Update `_meta/index.md`**: add the new folder to "Active
   experiments".

5. **Append to `_meta/log.md`**: `YYYY-MM-DD HH:MM new-experiment <slug>`.

6. **Commit the scaffold and print the hash** — an artifact write, no
   confirmation gate.

## Notes

- Runtime discipline (worktrees for destructive runs) per the
  project's `.claude/rules/experiments.md`.
- When the experiment finishes, update frontmatter `status:` and `result:`
  fields and move the folder out of "Active experiments" in
  `_meta/index.md`.
- Changing `splits.yaml` inside an HCE-scoped project is a breaking
  change — `~/claude-system/claude/rules/evaluation.md` clause 3.
