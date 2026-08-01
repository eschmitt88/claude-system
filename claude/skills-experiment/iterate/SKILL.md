---
name: iterate
description: One propose→implement loop cycle per invocation. Reads the latest implemented experiment's Diagnostics section, picks the strongest next_candidate, runs the /propose logic seeded with that candidate, presents the proposal, and pauses for user approval. On approval calls /implement. --experiment <path> targets a specific experiment; --chain <N> repeats up to N times without pausing; --chain-until <cond> halts on a budget / metric / count threshold; --ensemble <slug...> [--strategy auto|voting|stacking|averaging] runs a single combination cycle over completed experiments sharing a metric (kind: ensemble, members: frontmatter). Reads budget.yaml as implicit halting conditions each cycle. Appends every cycle to _meta/iteration_log.md.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# iterate

Drive the propose → implement → diagnose loop one step at a time, or
in a chain under explicit halting conditions.

## Arguments

- `--experiment <path>` — optional. Seed from this experiment's
  Diagnostics instead of the most recent implemented one.
- `--chain <N>` — optional. Run up to `N` full cycles without pausing
  between them. Can coexist with `--chain-until`.
- `--chain-until <condition>` — optional, repeatable. A halting
  condition string of the form `<key>:<op>:<value>`. Multiple
  conditions combine as **OR** — first to trip halts the chain.
- `--ensemble <slug-1> <slug-2> ... [--strategy <name>]` — run a
  single ensemble cycle over the named completed experiments instead
  of seeding from Diagnostics (see Ensemble mode below). Strategy ∈
  `auto | voting | stacking | averaging`, default `auto`. Not
  combinable with `--chain`.

### Chain-until conditions

Condition strings (`<key>:<op>:<value>`, e.g. `wall_hours:gte:8`,
`metric:gte:0.92`) are evaluated by `scripts/chain_budget.py` — the
grammar, the budget.yaml implicit-ceiling mapping, and the token/wall
arithmetic live there. For `key=metric` the metric name is inferred
from the most recent proposal's `expected_metric.name`.

`--chain N` and `--chain-until` can coexist; either halting condition
halts. A subagent hard failure always halts regardless of flags.

## Evaluation discipline (HCE)

Between cycles, read **only** each completed experiment's
`metrics.json` — never `final_metrics.json` or `test/`
(`~/claude-system/claude/rules/evaluation.md`).

## Steps (single cycle; default)

1. **Locate the seed experiment**:
   - If `--experiment` was given, use it.
   - Else find the experiment folder with the most recent
     `status: implemented` (check frontmatter of
     `experiments/*/README.md`).
   - **Bootstrap case (no implemented experiment yet):** look for the
     most recent proposal at `experiments/_proposals/*.md` with
     `status: proposed`. If exactly one exists, auto-invoke
     `/implement <proposal-path>` as cycle 0 and then continue from
     step 1 (now there's an implemented experiment to seed from).
     If zero proposals exist, abort and suggest running `/propose`
     from scratch. If multiple, list them and ask the user which to
     use. This removes the "`/iterate` aborts on a fresh project"
     failure mode that bit the Phase 5 smoke test.

2. **Read its `## Diagnostics`** section and its `metrics.json`. If
   the section is missing or `intended_effect_confirmed` is empty,
   stop and tell the user — the loop needs a real diagnosis.

3. **Pick the strongest `next_candidate`**. "Strongest" means: the
   one whose mechanism is most directly implicated by
   `intended_effect_confirmed` and `delta_from_prior`. If ambiguous,
   state your reasoning in one sentence and pick.

4. **Invoke the `/propose` logic with that candidate as the seed** —
   use the candidate text as the focus argument. Produce the proposal
   file exactly as `/propose` would.

5. **Present the proposal** and **pause for user approval**.

6. **On approval, call `/implement <proposal-path>`**. Relay its
   summary.

7. **Append one line to `_meta/iteration_log.md`** — create the file
   with a short header if missing:

   ```
   YYYY-MM-DD HH:MM  <seed-slug>  →  <proposal-slug>  →  <experiment-slug>  Δ<metric>=<delta>  budget{wall=<h>,tokens=<t>,experiments=<n>}
   ```

## Steps (`--chain` / `--chain-until` mode)

Run cycles back-to-back without pausing for approval (step 5 is
skipped). Each cycle performs steps 1-4, then 6, then 7.

### Before every cycle: budget check

Run the halting evaluator, passing your chain-local counters:

```bash
~/claude-system/coordinator/.venv/bin/python \
  ~/claude-system/scripts/chain_budget.py \
  --root <project> --chain-start <ISO> \
  [--until <k:op:v>]... \
  --experiments-completed <n> --consecutive-no-improvement <n> \
  [--metric-value <x>]
```

It reads `budget.yaml`'s ceilings as implicit conditions, sums
`_meta/token_log.ndjson` since chain start, checks disk against
`max_disk_gb`, and returns `{halt, tripped, totals}`. Halt when it says
halt, and name the tripped condition. Write one line per cycle to
`_meta/iteration_log.md` with a `budget{...}` suffix from `totals` so
the user can see the running numbers.

If budget.yaml is missing (`budget_present: false`), chain on explicit
`--chain N` / `--chain-until` only; log a warning on the first cycle.

### Halt conditions (any triggers a stop)

- Any `--chain-until` condition becomes true.
- `--chain N` cycles have all completed.
- Any `budget.yaml` implicit condition becomes true.
- An `/implement` call returns a hard failure (subagent error or
  missing `metrics.json`). Always halts regardless of flags.

On halt, write one final line to `_meta/iteration_log.md` naming the
halting reason and report it to the user.

## Ensemble mode (`--ensemble <slug...> [--strategy <name>]`)

One cycle whose "proposal" is *combine these members* (formerly the
standalone `/ensemble` skill). Motivated by MLE-STAR (arXiv
2506.15692): combining genuinely diverse members that target the same
metric is one of the most reliable sources of headroom in autonomous
ML loops. Two seeds of one config is noise reduction, not ensembling —
that's `/implement --seeds N`.

- **Members**: two or more experiments with `status: implemented` (or
  `done`) sharing the same primary metric and validation split (the
  HCE consistency clause). Read each member's README frontmatter,
  `metrics.json` (**never** `final_metrics.json` — ensembling is
  search-phase), and `results/` for per-example predictions
  (`predictions.parquet`, `val_preds.csv`, or similar). Refuse — don't
  fabricate, don't silently fall back to a weaker strategy — if any
  member is missing, still running, metric-mismatched, or lacks the
  predictions a strategy needs; name the offender.
- **Strategy** (when `auto`): predictions + continuous metric →
  averaging (or a learned blend if a held-out meta-split cleanly
  exists); classification → voting (soft when probabilities are
  present) or stacking with a clean meta-split. State the choice and
  reasoning in one sentence in the new README's `## Setup`.
- **Execution**: scaffold via `/new-experiment` with a slug naming the
  members compactly (e.g. `ensemble-mlp-xgb`). README frontmatter
  gains `kind: ensemble`, a `members:` list of slugs, and
  `strategy:`. `config.yaml` points at member predictions;
  `notes.qmd` computes the combined metric reproducibly. Run in the
  main agent (ensembling is cheap — no subagent) and write the
  combined number to the new experiment's `metrics.json` under the
  members' metric name.
- **Diagnostics**: fill honestly, as any cycle — did the combination
  beat the best single member on validation and by how much (cite
  `metrics.json`), which member drags, what to try next. A failed
  ensemble is useful signal; mark `intended_effect_confirmed: no`.
- **Logs**: `_meta/log.md` gets
  `YYYY-MM-DD HH:MM iterate --ensemble <members...> → <slug> Δ<metric>=<delta>`,
  plus the usual `_meta/iteration_log.md` line.

## Constraints

- This skill **does not** spawn a subagent itself. The only subagent
  in the loop is the one `/implement` spawns. `iterate` orchestrates;
  it does not execute.
- Cycles must be sequential, not parallel. No fan-out.
- In `--chain` / `--chain-until` mode, still show each proposal and
  each experiment summary to the user as you go — they should be able
  to interrupt at any cycle boundary.
