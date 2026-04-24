---
name: ensemble
description: /ensemble <slug-1> <slug-2> ... [--strategy auto|voting|stacking|averaging] takes N completed experiments targeting the same metric and produces a new ensemble experiment. Default strategy `auto` lets the model pick based on member types, metric, and predictions availability. Writes an experiment folder with kind: ensemble, a members: frontmatter list, and a proper Diagnostics section.
respects:
  - ~/.claude/rules/evaluation.md
---

# ensemble

Combine the predictions of N completed experiments into a new one.
Motivated by MLE-STAR (arXiv 2506.15692): ensembling diverse members
that individually target the same metric is one of the most reliable
sources of headroom in autonomous ML loops, with typical lift in the
3–5 point range when members are genuinely different.

## Arguments

- `<slug-1> <slug-2> ...` — two or more experiment slugs (kebab-case,
  matching existing `experiments/YYYY-MM-DD-<slug>/` folders). Every
  member must have `status: implemented` (or `done`) and a
  `metrics.json` targeting the same primary metric. Required.
- `--strategy <name>` — one of `auto | voting | stacking | averaging`.
  Default **`auto`** — the skill picks based on what's available.

## Steps

1. **Locate the active project** and resolve each member's path.
   Refuse if any member is missing, still running, or targets a
   different metric than the rest.

2. **Inspect members**. For each:
   - Read `README.md` frontmatter (status, hypothesis, metric).
   - Read `metrics.json` — **never** `final_metrics.json`; ensembling
     is a search-phase operation and must respect the HCE rule
     (`~/.claude/rules/evaluation.md`).
   - Check `results/` for per-example predictions (common names:
     `predictions.parquet`, `val_preds.csv`). Note which members
     expose predictions vs. only headline metrics.

3. **Pick the strategy** (when `--strategy auto`):
   - Predictions available for every member + continuous metric →
     `averaging` (or a learned blend if you judge a held-out
     meta-split makes sense).
   - Predictions available + classification → `voting` (soft if
     probabilities are present, hard otherwise) or `stacking` if a
     meta-split is cleanly available.
   - Predictions missing → refuse and tell the user which member is
     missing a predictions file. Do not fabricate.

   State the choice and the reasoning in one sentence in the new
   experiment's README under `## Setup`.

4. **Scaffold the ensemble experiment** via `/new-experiment
   <ensemble-slug>`. A good slug names the members compactly, e.g.
   `ensemble-mlp-xgb` or `ensemble-3seeds-avg`. In the new folder:

   - `README.md` frontmatter: set `kind: ensemble`, `hypothesis`
     reflecting the combination, and add
     ```yaml
     members:
       - "<slug-1>"
       - "<slug-2>"
     strategy: <averaging | voting | stacking>
     ```
   - `config.yaml` points at the members' predictions (paths
     relative to the project root).
   - `notes.qmd` loads each member's predictions and computes the
     combined metric. Keep it reproducible from `config.yaml`.

5. **Run the combination** (main agent, no subagent — ensembling is
   cheap). Write the combined number to `metrics.json` of the new
   experiment, with the same metric name each member used. Do not
   write `final_metrics.json` — that only happens at chain end via
   the final-scoring pass.

6. **Fill the Diagnostics section** of the new README honestly:
   - `intended_effect_confirmed` — did the combined metric beat the
     best single member on validation? By how much? Cite
     `metrics.json`.
   - `delta_from_prior` — delta vs. the best member; attribute it to
     diversity/agreement structure if you can characterize it.
   - `unexpected_findings` — any member dragging the ensemble down?
   - `next_candidates` — e.g. "try stacking with the top-3 members
     only", "add a diverse member that covers the failure cases in
     Diagnostics anchor `notes.qmd:bad-cases`".

7. **Append to `_meta/log.md`**:
   `YYYY-MM-DD HH:MM ensemble <members...> → <ensemble-slug> Δ<metric>=<delta>`.

## Constraints

- Two or more members required. Solo-member "ensembles" make no
  sense.
- Members must share a primary metric and a validation split — this
  is enforced by the HCE rule's consistency clause.
- Never read `test/` and never touch `final_metrics.json`.
- If a strategy can't be executed with the available artifacts (e.g.
  stacking without a clean meta-split), refuse — do not silently
  fall back to a weaker strategy.

## Notes

- Ensembling works best when members are **genuinely different**.
  Two seeds of the same config is noise reduction, not ensembling —
  that's what `/implement --seeds N` is for.
- A failed ensemble (combined metric worse than the best member) is
  also useful signal — write the Diagnostics honestly and mark
  `intended_effect_confirmed: no`.
