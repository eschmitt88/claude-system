---
name: implement
description: Execute a proposal inside a fresh subagent — the MLE-IDEATOR separation boundary and the only skill allowed to spawn a subagent. The subagent runs /new-experiment, writes code + config.yaml, executes dvc exp run, captures metrics and results, then writes a structured Diagnostics section to README.md. On success, files the proposal under experiments/_proposals/_done/ with status: implemented; on hard failure, files it under _proposals/_failed/ with the captured error. Supports --seeds N for pass@k multi-seed runs and --implementer-model <slug> to pick the subagent model (default from budget.yaml).
respects:
  - ~/.claude/rules/evaluation.md
---

# implement

Turn a proposal into a run. This is the **only** skill in the framework
that is allowed to spawn a subagent.

## Arguments

- `<proposal-path>` — path to a file under `experiments/_proposals/`
  (or `experiments/_proposals/_expansions/<parent>/`). Required.
  Refuse if the file does not exist or its frontmatter `status:` is
  anything other than `proposed`.

- `--seeds <N>` — optional. Run the experiment `N` times with
  different seeds and report aggregated metrics as `mean ± std` in
  `metrics.json` and in the Diagnostics section. The Diagnostics
  `intended_effect_confirmed` and `overfitting_signal` fields reflect
  the aggregated view, not any single seed. Motivated by MLE-bench's
  pass@k result (o1-preview: pass@1 16.9% → pass@8 34.1%): the same
  config run with different seeds genuinely finds different local
  optima, and a mean±std report is more honest signal than a single
  number.

  The subagent exposes the seed either via `config.yaml` `seed:` (the
  default template field) or a CLI arg, whichever the experiment's
  entry point consumes. N=1 is the no-op default.

- `--implementer-model <slug>` — optional. Model for the implementer
  subagent. Resolution order, highest precedence first:

  1. this CLI flag
  2. the project's `budget.yaml` field `models.implementer`
  3. the main-session model (inherited)

  The template default is `opus` for both roles — a floating alias that
  resolves to the latest Opus release, so the box tracks new Opus
  versions without edits. Pass the slug straight through to the Agent
  tool's `model` parameter, which accepts `opus`/`sonnet`/`haiku` aliases
  as well as concrete IDs (e.g. `claude-opus-4-8`). A capability- or
  cost-split config (e.g. a `haiku`/`sonnet` implementer, or a pinned
  version for reproducibility) slots in by editing `budget.yaml` alone —
  no skill rewrite. Motivated by R&D-Agent's hybrid-backend pattern.

## Steps

1. **Resolve the proposal path** in the active project.

2. **Read `budget.yaml`** at the project root (if present). Use it to
   resolve `--implementer-model`'s default and to surface the
   hardware hints to the subagent in step 3. If `budget.yaml` is
   missing, inherit the main-session model and skip the hardware
   block.

3. **Assemble the subagent prompt.** Include **only** these inputs
   (nothing else from the current conversation):

   a. The full text of the proposal file.
   b. `~/.claude/CLAUDE.md` (durable principles).
   c. The project-root `CLAUDE.md`.
   d. `~/.claude/rules/evaluation.md` (the HCE rule — non-negotiable).
   e. Any other `.claude/rules/*.md` whose scope covers
      `experiments/**` or paths the proposal will touch. Include each
      file's full text.
   f. The resolved `budget.yaml` hardware block (plain YAML).

   Prepend a short preamble telling the subagent:
   - You are the IMPLEMENTER. The main agent is the IDEATOR. Do not
     re-argue the hypothesis — execute it. (Label it MLE when the
     proposal is ML work, but the contract is the same regardless
     of domain: literature triage, scraping, analysis, ML — all
     valid.)
   - If the project opts into HCE (see
     `~/.claude/rules/evaluation.md`): `test/` is off-limits,
     `metrics.json` is the search signal, `final_metrics.json` is
     never written during search. Skip this clause entirely for
     projects without an evaluation holdout.
   - **Idempotency**: if the experiment folder at
     `experiments/YYYY-MM-DD-<slug>/` already exists (because
     `/mle-task`, `/new-experiment`, or another upstream skill
     scaffolded it), **skip `/new-experiment`** and work in the
     existing folder. Otherwise run `/new-experiment <slug>` with
     `<slug>` from the proposal frontmatter.
   - You may write code, edit `config.yaml`, and run `dvc exp run`.
   - You must capture `metrics.json` (validation) and populate
     `results/`.
   - If `--seeds N` was passed: run the experiment N times with the
     seeds `[42, 43, ..., 42+N-1]` (or a set of your choice,
     recorded in `config.yaml`), collect per-seed `metrics.json`-style
     dicts into `results/per_seed.json`, and write aggregated
     mean/std into the top-level `metrics.json`.
   - You must write a `## Diagnostics` section into the experiment's
     `README.md` with the exact fields in step 5 below, anchoring
     every concrete claim to a file:line or metrics path.
   - **Do not write to `_meta/log.md`.** The main agent owns logging
     and will append the canonical line after you return.
   - Return a ≤200-word summary to the parent. Do not dump logs.

4. **Spawn exactly one subagent** via the Agent tool (subagent_type:
   `general-purpose`), passing the resolved model slug via the `model`
   parameter. One per invocation — no fan-out, no retry loop.

5. **The subagent must emit a `## Diagnostics` section** with these
   fields (flat, one line each except `next_candidates`):

   ```markdown
   ## Diagnostics

   - intended_effect_confirmed: <yes | no | partial> — <one-line evidence with anchor>
   - leakage_check: <method used> — <finding>
   - overfitting_signal: train=<x> val=<y> gap=<z> — <interpretation> (from metrics.json)
   - delta_from_prior: vs <related_prior_slug>, <metric_delta> attributed to <cause> (metrics.json)
   - unexpected_findings: <one or two sentences, or "none">
   - seeds_run: <list of seeds | "1 (single run)">
   - metric_aggregation: <"single-run" | "mean ± std over N seeds">
   - next_candidates:
     - <one-sentence proposal 1>
     - <one-sentence proposal 2>
   ```

   At least two `next_candidates` are required; more are welcome.
   Every concrete claim must carry an anchor — `train.py:42-58`,
   `metrics.json:val_acc`, a `[[literature/...]]` wikilink, or a
   `notes.qmd:cell-label`. Unanchored claims are flagged by `/lint`.

6. **On subagent return (success)**:

   - Move the proposal to
     `experiments/_proposals/_done/YYYY-MM-DD-<slug>.md`.
     (Expansion children are moved out of
     `_expansions/<parent>/` into `_done/` so `/iterate` finds them
     alongside their siblings.)
   - Update its frontmatter: `status: implemented` and add
     `experiment: experiments/YYYY-MM-DD-<slug>/`.
   - Append to `_meta/log.md`:
     `YYYY-MM-DD HH:MM implement <slug> → experiments/YYYY-MM-DD-<slug>/ seeds=<N> model=<slug>`.
   - Relay the subagent's ≤200-word summary to the user verbatim.
   - The proposal move/update is an artifact write (filing a completed
     run) — no confirmation gate; show the diff of what changed.

7. **On subagent return (hard failure)** — the subagent exited with
   an error, the run crashed, or `metrics.json` is missing:

   - Move the proposal to
     `experiments/_proposals/_failed/YYYY-MM-DD-<slug>.md`.
   - Update frontmatter: `status: failed`, add
     `error: "<captured one-line error>"`,
     `attempted_at: YYYY-MM-DD HH:MM`, and
     `model: <resolved implementer model slug>`.
   - Append to `_meta/log.md`:
     `YYYY-MM-DD HH:MM implement-failed <slug>: <error>`.
   - Artifact write (filing a failed run) — no confirmation gate; show
     the diff of what changed.

## Constraints

- **One subagent per invocation.** If the run needs multiple phases,
  the subagent sequences them internally. `--seeds N > 1` is a single
  invocation; the subagent handles the loop internally.
- **No subagent context leakage.** Do not pass the current
  conversation transcript, other proposals, or unrelated project
  files into the prompt. The listed inputs in step 3 are the whole
  allow-list.
- **Do not re-open the hypothesis.** If you (the main agent) now
  disagree with the proposal, stop and say so rather than silently
  editing it. Proposals are edited via `/propose`, not `/implement`.
- **HCE rule** — the subagent must not read `test/` and must not write
  `final_metrics.json`. See `~/.claude/rules/evaluation.md`.
