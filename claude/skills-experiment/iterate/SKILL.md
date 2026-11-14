---
name: iterate
description: One propose→implement cycle per call, seeded from the latest experiment's Diagnostics. --chain N / --chain-until <cond> run cycles unattended under budget.yaml ceilings; --ensemble <slugs> combines completed experiments. Logs every cycle to _meta/iteration_log.md.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# iterate

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Drive the propose → implement → diagnose loop one step at a time, or in a
chain under explicit halting conditions. It orchestrates only: the single
subagent in the loop is the one `/implement` spawns, and cycles run in
sequence, never in parallel.

Between cycles, read only each experiment's `metrics.json`, never
`final_metrics.json` or `test/` (`evaluation.md`).

## Arguments

- `--experiment <path>`: seed from this experiment instead of the most
  recent implemented one.
- `--chain <N>`: up to N cycles without pausing.
- `--chain-until <key>:<op>:<value>`: repeatable; the first condition to
  trip halts (e.g. `wall_hours:gte:8`, `metric:gte:0.92`). The grammar and
  arithmetic live in `scripts/chain_budget.py`. For `metric`, the name
  comes from the latest proposal's `expected_metric.name`.
- `--ensemble <slug> <slug> … [--strategy auto|voting|stacking|averaging]`:
  one combination cycle (below). Not combinable with `--chain`.

## One cycle

1. **Find the seed experiment**: `--experiment`, else the most recent with
   `status: implemented`. If none exists yet, bootstrap: with exactly one
   `status: proposed` proposal, run `/implement` on it as cycle 0 and
   continue; with none, stop and suggest `/propose`; with several, ask
   which.

2. **Read its `## Diagnostics`** and `metrics.json`. If the section is
   missing or `intended_effect_confirmed` is empty, stop: the loop needs a
   real diagnosis.

3. **Pick the strongest `next_candidate`**: the one whose mechanism is most
   directly implicated by `intended_effect_confirmed` and
   `delta_from_prior`. Say why in a sentence.

4. **Write the proposal** exactly as `/propose` would, with that candidate
   as the focus.

5. **Confirm it.** Choosing a proposal is hypothesis selection (`agency.md`,
   Confirmation principle): pause for approval under `agency: standard`;
   continue under `agency: max` when the verdict is not `hold`.

6. **Run `/implement <proposal-path>`** and relay its summary.

7. **Log** one line to `_meta/iteration_log.md` (create it with a short
   header if missing):

   ```
   YYYY-MM-DD  <seed-slug>  →  <proposal-slug>  →  <experiment-slug>  Δ<metric>=<delta> band=<std|none>  budget{wall=<h>,tokens=<t>,experiments=<n>}
   ```

   On a pivot cycle, append ` redirect=<axis>`.

## Chains (`--chain`, `--chain-until`)

Cycles run back to back and step 5 does not pause, but still show each
proposal and each experiment summary as you go, so the user can interrupt
at a cycle boundary.

**Before every cycle**, run the halting evaluator with your chain-local
counters:

```bash
~/claude-system/coordinator/.venv/bin/python \
  ~/claude-system/scripts/chain_budget.py \
  --root <project> --chain-start <ISO> \
  [--until <k:op:v>]... \
  --experiments-completed <n> --consecutive-no-improvement <n> \
  [--metric-value <x>]
```

It treats `budget.yaml`'s ceilings as implicit conditions, sums the token
log since chain start, checks disk, and returns `{halt, tripped, totals}`.
Halt when it says so and name the tripped condition. Put `totals` in the
log line's `budget{…}`. With no `budget.yaml`, chain on the explicit flags
only and log a warning on the first cycle.

The chain also halts when `--chain N` cycles are done, and always on an
`/implement` hard failure. On halt, write a final log line naming the
reason and report it.

**What counts as an improvement.** `--consecutive-no-improvement` counts
consecutive cycles that did not beat the chain's best by more than the
noise band. When either run used `--seeds N>1`, the band is the larger of
the two `std` values in their Diagnostics. A single-run metric has no band,
so any strictly positive delta counts, and the log says `band=none`. Reset
the counter only on an improvement beyond the band: a "new best" inside it
is a coin flip, and counting it stops the ceiling from ever firing.

**Pivot before the stall halt.** When the counter is one below
`max_consecutive_no_improvement`, the next cycle must change the axis, not
refine it. In step 3, reject any candidate that keeps the stalled cycles'
backbone, representation, objective and validation scheme. Pick one that
changes at least one of them, or reopen a `next_candidate` an earlier
cycle in this chain passed over, and name the changed axis in a sentence.
Judge the pivot against the chain's best under the same band. If it also
fails, the counter reaches the ceiling and the chain halts as before. With
a ceiling of 1, or no `budget.yaml`, there is no pivot cycle. (Left alone,
agents refine the stalled axis, and a "consider something different" nudge
does not change that.)

## Ensemble mode

One cycle whose proposal is "combine these members". Combining genuinely
diverse members on one metric is among the most reliable sources of
headroom in autonomous ML loops (MLE-STAR). Two seeds of one config is
noise reduction, not ensembling; that is `/implement --seeds N`.

- **Members**: two or more experiments with `status: implemented` or
  `done`, sharing the primary metric and the validation split. Read each
  one's frontmatter, `metrics.json` and the per-example predictions under
  `results/`. If a member is missing, still running, on a different
  metric, or lacks the predictions the strategy needs, refuse and name it.
  Don't fall back to a weaker strategy silently.
- **Strategy** under `auto`: continuous metric → averaging (or a learned
  blend if a clean held-out meta-split exists); classification → voting
  (soft when probabilities exist) or stacking with a clean meta-split.
  State the choice in the new README's `## Setup`.
- **Run it in the main agent** (it is cheap): scaffold with
  `/new-experiment` under a slug naming the members
  (`ensemble-mlp-xgb`); README frontmatter gains `kind: ensemble`,
  `members:` and `strategy:`; `config.yaml` points at the member
  predictions; `notes.qmd` computes the combined metric reproducibly;
  write it to `metrics.json` under the members' metric name.
- **Diagnose honestly**: did it beat the best single member on validation,
  by how much, which member drags. A failed ensemble is signal:
  `intended_effect_confirmed: no`.
- **Log** `YYYY-MM-DD iterate --ensemble <members...> → <slug> Δ<metric>=<delta>`
  in `_meta/log.md`, plus the usual iteration-log line.
