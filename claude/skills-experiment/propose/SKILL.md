---
name: propose
description: Ideation only. /propose [concept-or-moc] writes one experiment proposal (falsifiable hypothesis, grounded rationale, expected metric, risks) to experiments/_proposals/. --expand <proposal> [--n N] writes up to N sibling proposals that test the same claim differently. No code, no scaffolding.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# propose

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Produce a decision document, not a run. This is the ideation half of the
ideator/implementer split: no code, no scaffolding, no `dvc.yaml` or
`config.yaml` edits, no subagent. A proposal stays in the main context so
it can be argued with before compute is committed.

`/propose [<concept-or-moc>]` focuses on that concept or MoC (a name or a
path); with no argument, on the tail of `NOTES.md`.

## Ground it

Read, and cite only what you read:

- everything under `concepts/`;
- the 10 most recently modified `literature/**/*.md`;
- the 5 most recent `experiments/*/README.md` with each `metrics.json`
  (never `final_metrics.json` or `test/`; `evaluation.md`);
- the tail of `NOTES.md`, and `budget.yaml`, so runtime and risks are
  judged against the remaining headroom;
- the focus file and the files it links to, one hop.

If that is too thin to ground a falsifiable hypothesis, say so and stop.
Two competing ideas are two proposals, not one hedged proposal.

## The proposal

`experiments/_proposals/YYYY-MM-DD-<slug>.md` (refuse if it exists):

```yaml
---
kind: proposal
slug: <slug>
date: YYYY-MM-DD
status: proposed
hypothesis: "<one-sentence falsifiable claim>"
rationale: "<≤5 sentences, grounded in cited notes>"
reads:
  - "[[literature/papers/foo]]"
  - "[[concepts/bar]]"
expected_metric:
  name: <metric name>
  target: <numeric target>
  direction: higher-is-better  # or lower-is-better
design_sketch:
  - <bullet>
risks:
  - <likely failure mode>
related_prior:
  - <prior experiment slug this builds on or contradicts>
estimated_runtime: <e.g. "15 min on CPU", "2 h on single GPU">
---
```

Flat YAML only. Every `reads:` entry is a file you opened, and every
`related_prior:` slug is an existing `experiments/*/` folder. `status:`
stays `proposed`.

Below it, 200–400 words of prose (not bullets): why this is worth testing
now, what in the cited notes motivates it, and how the expected metric
movement would change your beliefs.

**Persist** per the Confirmation principle (`agency.md`). A proposal is
hypothesis selection: show it and confirm under `agency: standard`; write
and continue under `agency: max`. Then append
`YYYY-MM-DD propose <slug>` to `_meta/log.md`.

## Expand mode: `--expand <proposal-path> [--n N]`

Breadth on one hypothesis: up to N (default 3) sibling proposals that test
the parent's claim through substantively different approaches
(architecture, training regime, features, evaluation strategy, data scale,
prior integration). N is a cap. Two children differing only in a
hyperparameter waste a slot; write fewer and say so.

- The parent must be under `experiments/_proposals/` with
  `status: proposed`. Read it and its `reads:`. Do not modify it.
- Each child is an ordinary proposal plus `parent: "<parent-slug>"` and
  `expansion_axis: "<what varies>"`, at
  `experiments/_proposals/_expansions/<parent-slug>/<child-slug>.md`.
- Log `YYYY-MM-DD propose --expand <parent-slug> → <n> children`.
- `/lint` flags children older than 7 days that were never implemented.
