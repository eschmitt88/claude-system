---
name: new-experiment
description: Scaffold an experiment folder at experiments/YYYY-MM-DD-<slug>/ with README.md, notes.qmd, config.yaml, results/, log.md, metrics.json. Pre-fills frontmatter from _meta/templates/experiment.md. If the project opts into HCE (has a splits.yaml or test/ directory), also copies the split spec — otherwise splits.yaml is skipped.
respects:
  - ~/.claude/rules/evaluation.md
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
     `metrics.json` when the project is in HCE mode, else the
     experiment's own result file). Preserve the template verbatim
     so `/implement` and `/iterate` can fill it after the run.
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

4. **HCE mode (optional).** Check whether this project opts into the
   HCE rule by looking for any of:
   - a `splits.yaml` at the project root;
   - a `test/` directory or symlink under any existing experiment;
   - an `evaluation_mode: hce` declaration in the project CLAUDE.md.

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
   - **Do not** create `final_metrics.json` here. It is written only
     by the final-scoring pass at chain end, per the HCE rule
     (`~/.claude/rules/evaluation.md`).

   **If not opted-in:** skip `splits.yaml` entirely. The experiment
   has no held-out evaluation. `metrics.json` is still the canonical
   metric file — it just has no "val vs test" semantics.

5. **Update `_meta/index.md`**: add the new folder to "Active
   experiments".

6. **Append to `_meta/log.md`**: `YYYY-MM-DD HH:MM new-experiment <slug>`.

7. **Write all scaffold files and commit.** Agentic workflow —
   no confirmation gate. After writing the folder + files, run:

   ```sh
   git add -A
   git commit -m "new-experiment YYYY-MM-DD-<slug>: scaffold"
   ```

   Then print the commit hash. Rationale: git is the memory
   layer per `CLAUDE.md`, and commits are reversible
   (`git revert`), so the default is to commit.

## Notes

- Destructive or long-running runs against this experiment should happen
  in a Git worktree under `.worktrees/`, not in the primary checkout.
- When the experiment finishes, update frontmatter `status:` and `result:`
  fields and move the folder out of "Active experiments" in
  `_meta/index.md`.
- Changing `splits.yaml` inside an HCE-scoped project is a breaking
  change — record it in `docs/decisions/`. See
  `~/.claude/rules/evaluation.md` clause 3 for the scoping rules.
