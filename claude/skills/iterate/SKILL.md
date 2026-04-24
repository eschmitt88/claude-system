---
name: iterate
description: One propose→implement loop cycle per invocation. Reads the latest implemented experiment's ## Diagnostics, picks the strongest next_candidate, runs the /propose logic seeded with that candidate, presents the proposal, and pauses for user approval. On approval calls /implement. --experiment <path> targets a specific experiment; --chain <N> repeats up to N times without pausing; --chain-until <cond> halts on a budget / metric / count threshold. Reads budget.yaml as implicit halting conditions each cycle. Appends every cycle to _meta/iteration_log.md.
respects:
  - ~/.claude/rules/evaluation.md
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

### Chain-until grammar

```
<key>   ∈ { metric, wall_hours, tokens_spent, consecutive_no_improvement, experiments_completed }
<op>    ∈ { gte, lte, eq }
<value> is numeric (ints or floats); or for key=metric, numeric with
        the metric name inferred from the most recent proposal's
        expected_metric.name.
```

Examples:

```
--chain-until wall_hours:gte:8
--chain-until tokens_spent:gte:2000000
--chain-until consecutive_no_improvement:gte:3
--chain-until experiments_completed:gte:5
--chain-until metric:gte:0.92
```

`--chain N` and `--chain-until` can coexist; either halting condition
halts. A subagent hard failure always halts regardless of flags.

## Evaluation discipline (HCE)

Between cycles, `/iterate` reads **only** each completed experiment's
`metrics.json` (validation split — this is the search signal). It
does **not** read `final_metrics.json` and does **not** read anything
under `test/`. The final-scoring pass is explicit and outside the
loop. See `~/.claude/rules/evaluation.md`.

## Steps (single cycle; default)

1. **Locate the seed experiment**:
   - If `--experiment` was given, use it.
   - Else find the experiment folder with the most recent
     `status: implemented` (check frontmatter of
     `experiments/*/README.md`). If none exists, abort and suggest
     running `/propose` from scratch.

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

Read `budget.yaml` at the project root. Treat these fields as
**implicit halting conditions** that compose with any explicit
`--chain-until`:

| budget.yaml field                      | implicit condition                  |
| -------------------------------------- | ----------------------------------- |
| `max_wall_hours`                       | `wall_hours:gte:<value>`            |
| `max_tokens`                           | `tokens_spent:gte:<value>`          |
| `max_experiments`                      | `experiments_completed:gte:<value>` |
| `max_consecutive_no_improvement`       | `consecutive_no_improvement:gte:<value>` |
| `max_disk_gb`                          | disk-usage check — see below        |

`tokens_spent` is the running sum from `_meta/token_log.ndjson` (written by
the `token_logger` Stop hook). `wall_hours` is counted from the start of
the chain. `experiments_completed` and `consecutive_no_improvement` are
counted from the start of the chain. `max_disk_gb` is checked by comparing
`du -s <project-root>` to the limit — go above and halt.

Write one line per cycle to `_meta/iteration_log.md` in a `budget{...}`
suffix so the user can see the running totals.

If budget.yaml is missing, chain on explicit `--chain N` /
`--chain-until` only; log a warning on the first cycle.

### Halt conditions (any triggers a stop)

- Any `--chain-until` condition becomes true.
- `--chain N` cycles have all completed.
- Any `budget.yaml` implicit condition becomes true.
- An `/implement` call returns a hard failure (subagent error or
  missing `metrics.json`). Always halts regardless of flags.

On halt, write one final line to `_meta/iteration_log.md` naming the
halting reason and report it to the user.

## Constraints

- This skill **does not** spawn a subagent itself. The only subagent
  in the loop is the one `/implement` spawns. `iterate` orchestrates;
  it does not execute.
- Cycles must be sequential, not parallel. No fan-out.
- In `--chain` / `--chain-until` mode, still show each proposal and
  each experiment summary to the user as you go — they should be able
  to interrupt at any cycle boundary.
- Never read `final_metrics.json` or `test/` from inside the loop.
  That is a lint-level hard failure under the HCE rule.
