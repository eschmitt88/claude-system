---
name: new-experiment
description: Scaffold an experiment folder at experiments/YYYY-MM-DD-<slug>/ with README.md, notes.qmd, config.yaml, results/, log.md, metrics.json. Pre-fills frontmatter from _meta/templates/experiment.md. Copies the project's split spec (splits.yaml) so every experiment shares the same seeded validation and test splits per the HCE rule.
respects:
  - ~/.claude/rules/evaluation.md
---

# new-experiment

Create a new experiment folder in the active project.

## Arguments

- `<slug>` — kebab-case name for the experiment. Required.

## Steps

1. **Locate the active project** (same rule as `/wrap`): nearest ancestor
   with both `CLAUDE.md` and `_meta/`.

2. **Compute the folder name**: `experiments/YYYY-MM-DD-<slug>/` using
   today's local date. Refuse if that folder already exists.

3. **Create the folder and files**:

   - `README.md` — seeded from `_meta/templates/experiment.md`, with
     frontmatter `slug`, `date`, `status: running` pre-filled. The
     template ships with a `## Diagnostics` fill-in-the-blank section
     (fields: `intended_effect_confirmed`, `leakage_check`,
     `overfitting_signal`, `delta_from_prior`, `unexpected_findings`,
     `seeds_run`, `metric_aggregation`, `next_candidates`) and notes
     which metrics file each field references (default:
     `metrics.json`, i.e. validation split). Preserve the template
     verbatim so `/implement` and `/iterate` can fill it after the run.
   - `config.yaml` — minimal stub:
     ```yaml
     # Inputs, hyperparameters, seeds for this experiment.
     seed: 42
     ```
   - `notes.qmd` — Quarto stub with a YAML header and one empty code
     chunk.
   - `results/.gitkeep` — empty placeholder.
   - `log.md` — header only.
   - `metrics.json` — `{}` so DVC has something to track
     (validation-split metrics; the search signal).
   - **Do not** create `final_metrics.json` here. It is written only
     by the `dvc repro final_eval` pass at chain end, per the HCE
     rule (`~/.claude/rules/evaluation.md`).
   - `splits.yaml` — **copy** from the project root if it exists.
     All experiments in a project share the same seeded validation
     and test splits. If the project root has no `splits.yaml`, emit
     a stub:
     ```yaml
     # Shared data splits for this project. All experiments reference
     # this file; changing it invalidates cross-experiment comparisons.
     # Promote to the project root after filling in.
     seed: 42
     val_fraction: 0.1
     test_fraction: 0.1
     # dataset-specific identifiers go here
     ```
     and tell the user: "No project-level `splits.yaml` found — I
     emitted a stub inside this experiment. Move it to the project
     root and re-run if other experiments should share it."

4. **Update `_meta/index.md`**: add the new folder to "Active
   experiments".

5. **Append to `_meta/log.md`**: `YYYY-MM-DD HH:MM new-experiment <slug>`.

6. **Show the diff and wait for confirmation** before writing.

## Notes

- Destructive or long-running runs against this experiment should happen
  in a Git worktree under `.worktrees/`, not in the primary checkout.
- When the experiment finishes, update frontmatter `status:` and `result:`
  fields and move the folder out of "Active experiments" in
  `_meta/index.md`.
- Changing `splits.yaml` is a **project-level decision**, not an
  experiment-level one. Record changes in `docs/decisions/`.
