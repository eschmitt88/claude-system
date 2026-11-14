---
name: implement
description: /implement <proposal-path> runs a proposal in a fresh subagent (the ideator/implementer boundary, and the experiment loop's only subagent): scaffolds the experiment, writes code, runs it, records metrics and a Diagnostics section, then files the proposal under _done/ or _failed/. --seeds N for multi-seed runs; --implementer-model to choose the subagent model.
respects:
  - ~/claude-system/claude/rules/evaluation.md
---

# implement

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Turn a proposal into a run, inside one fresh subagent. The implementer
sees the proposal and the rules, and none of the ideation that led to it,
so it executes the hypothesis without re-arguing it.

## Arguments

- `<proposal-path>`: a file under `experiments/_proposals/` (or its
  `_expansions/<parent>/`) with `status: proposed`. Refuse anything else.
- `--seeds <N>`: run N times with different seeds and report `mean ± std`
  in `metrics.json` and Diagnostics. The same config genuinely finds
  different optima per seed (MLE-bench pass@1 16.9% → pass@8 34.1%), so an
  aggregate is more honest than one number. Default 1.
- `--implementer-model <slug>`: the subagent's model. Precedence: this
  flag, then `models.implementer` in `budget.yaml`, then the main
  session's model. Aliases (`opus`, `sonnet`, `haiku`) and concrete IDs
  both work; pass it straight to the Agent tool's `model` parameter.

## The subagent's brief

Spawn exactly one `general-purpose` subagent, with the resolved model. One
per invocation: no fan-out and no retry loop. Multi-phase or multi-seed
work is sequenced inside it.

Give it these inputs and nothing else from this conversation (no
transcript, no other proposals):

- the full proposal;
- `~/.claude/CLAUDE.md` and the project's `CLAUDE.md`;
- `~/claude-system/claude/rules/evaluation.md`, and any `.claude/rules/*.md`
  that covers `experiments/**` or paths the proposal will touch, in full;
- the `hardware:` block of `budget.yaml`.

And tell it:

- It is the implementer; the main agent is the ideator. Execute the
  hypothesis; do not re-argue it.
- If the project is under HCE: `test/` is off-limits, `metrics.json` is the
  validation-split search signal, and `final_metrics.json` is never
  written during search.
- Work in `experiments/YYYY-MM-DD-<slug>/` if it already exists; otherwise
  create it with `/new-experiment <slug>`.
- Write the code, edit `config.yaml`, run it (`dvc exp run`), write
  `metrics.json` and populate `results/`.
- With `--seeds N`: seeds `42 … 42+N-1` (or its own choice, recorded in
  `config.yaml`), per-seed results in `results/per_seed.json`, aggregated
  mean and std in `metrics.json`.
- Write the `## Diagnostics` section below into the experiment's
  `README.md`.
- Do not write to `_meta/log.md`; the main agent logs.
- Return a summary of at most 200 words. No logs.

If the implementer is a smaller model than the one that wrote the proposal
(`haiku` or `sonnet` under an Opus or Fable ideator), also spell out what a
peer would work out alone: the entry point to write, the exact command
that produces `metrics.json`, and where each required output goes.

## Diagnostics (the contract `/iterate`, `/wrap`, `/lint` and the dashboard read)

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

At least two `next_candidates`. Every concrete claim carries an anchor
(`train.py:42-58`, `metrics.json:val_acc`, a `[[literature/...]]` link, a
`notes.qmd` cell label); `/lint` flags unanchored claims.

## When it returns

**Success:**

- Move the proposal to `experiments/_proposals/_done/YYYY-MM-DD-<slug>.md`
  (expansion children too, so `/iterate` finds them beside their
  siblings). Set `status: implemented` and add
  `experiment: experiments/YYYY-MM-DD-<slug>/`.
- Log `YYYY-MM-DD implement <slug> → experiments/YYYY-MM-DD-<slug>/ seeds=<N> model=<slug>`.
- Relay the subagent's summary verbatim.

**Hard failure** (the subagent errored, the run crashed, or `metrics.json`
is missing):

- Move the proposal to `experiments/_proposals/_failed/`. Set
  `status: failed` and add `error: "<one line>"`,
  `attempted_at: YYYY-MM-DD` and `model: <slug>`.
- Log `YYYY-MM-DD implement-failed <slug>: <error>`.

Filing either way is an artifact write: no confirmation gate.

If you now disagree with the proposal, stop and say so. Proposals are
changed through `/propose`, never edited here.
