---
name: propose
description: Strategic ideation for the active research project — no implementation. Reads concepts/, the 10 most recently modified literature notes, and the 5 most recent experiment READMEs + their metrics.json. Emits one proposal file at experiments/_proposals/YYYY-MM-DD-<slug>.md with flat YAML frontmatter (hypothesis, rationale, reads, expected_metric, design_sketch, risks, related_prior, estimated_runtime, status) plus a prose argument. --expand <proposal-path> [--n N] switches to breadth-first mode, emitting up to N (default 3) sibling proposals of an existing one under experiments/_proposals/_expansions/<parent-slug>/ with parent: and expansion_axis: frontmatter. Does not scaffold an experiment, write code, or touch dvc.yaml.
respects:
  - ~/.claude/rules/evaluation.md
  - ~/.claude/rules/agency.md
---

# propose

Produce a single experiment proposal. This is the ideation half of the
MLE-IDEATOR split: **no code, no scaffolding, no dvc.yaml edits**. The
output is a decision document.

## Arguments

- `[<concept-or-moc>]` — optional. A concept name, MoC name, or path under
  `concepts/` or `mocs/`. If present, the proposal focuses on that theme.
  If absent, synthesize from the active `NOTES.md` tail.
- `--expand <proposal-path> [--n N]` — switch to expand mode (below):
  breadth-first siblings of an existing proposal instead of one new
  proposal. Mutually exclusive with the concept/MoC argument.

## Steps

1. **Locate the active project** (nearest ancestor with both `CLAUDE.md`
   and `_meta/`). Refuse if none.

2. **Gather context** — read the following, and nothing else from the
   filesystem beyond templates:
   - all files under `concepts/`
   - the **10 most recently modified** `literature/**/*.md`
   - the **5 most recent** `experiments/*/README.md` and each sibling
     `metrics.json` (validation split — the search signal; **do not**
     read `final_metrics.json` or anything under `test/`, see
     `~/.claude/rules/evaluation.md`)
   - the last 50 lines of `NOTES.md`
   - `budget.yaml` at the project root (if present) — so
     `estimated_runtime:` and `risks:` can be grounded against the
     remaining headroom (wall hours, tokens, disk)
   - if a concept/MoC argument was given, that file plus any files it
     wikilinks to (one hop)

3. **Pick a slug**. Derive a short kebab-case slug from the core idea.
   The proposal path is
   `experiments/_proposals/YYYY-MM-DD-<slug>.md` using today's local
   date. Create `experiments/_proposals/` if missing. Refuse if the
   target path already exists.

4. **Draft the proposal** with this frontmatter (all flat YAML, no
   nested schemas):

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
     - <bullet 1>
     - <bullet 2>
   risks:
     - <likely failure mode 1>
     - <likely failure mode 2>
   related_prior:
     - <prior experiment slug this builds on or contradicts>
   estimated_runtime: <e.g. "15 min on CPU", "2 h on single GPU">
   ---
   ```

   Every `reads:` entry must be a real file you actually opened in step 2
   — no decorative citations. `related_prior:` slugs must match existing
   `experiments/*/` folders.

5. **Write the body** below the frontmatter: a longer prose argument
   (not bullets) explaining why this hypothesis is worth testing now,
   what evidence from the cited notes motivates it, and how the
   expected metric movement would update your beliefs. Keep it tight —
   aim for 200–400 words.

6. **Show the diff** for the single new file and wait for confirmation
   before writing. Do not create any other files. Do not touch
   `dvc.yaml`, `config.yaml`, or any experiment folder.

7. **After writing**, append one line to `_meta/log.md`:
   `YYYY-MM-DD HH:MM propose <slug>`.

## What this skill does NOT do

- Does not run `/new-experiment`.
- Does not write Python, configs, or DVC stages.
- Does not spawn a subagent. Proposals are a main-context artifact so
  you can argue with them before committing compute.
- Does not set `status:` to anything other than `proposed`.

## Expand mode (`--expand <proposal-path> [--n N]`)

Breadth-first ideation on a single hypothesis (formerly the standalone
`/expand` skill): emit up to N (default **3**) sibling proposals that
test the parent's claim via substantively different approaches —
architecture, training regime, feature engineering, evaluation
strategy, data scale, prior integration. You pick the axes; genuine
diversity is the bar. Treat N as a cap — two children differing only
in a hyperparameter are wasted slots, so emit fewer and say so rather
than pad.

Deltas from the default mode:

- The parent must live under `experiments/_proposals/` (not `_done/`,
  not `_failed/`) with `status: proposed`. Read it in full plus the
  files in its `reads:` (one hop) so children ground in the same
  evidence. **Do not modify the parent** — it stays individually
  implementable.
- Each child is an ordinary proposal (same frontmatter keys, body
  rules, and step-6 confirmation as above; fresh `date:`,
  `status: proposed`) plus two extra fields:
  `parent: "<parent-slug>"` and
  `expansion_axis: "<one-line label for what varies>"`.
- Path: `experiments/_proposals/_expansions/<parent-slug>/<child-slug>.md`,
  child slugs reflecting the axis (e.g. `…-ema`, `…-loss-mask`).
- Log line: `YYYY-MM-DD HH:MM propose --expand <parent-slug> → <n> children`.

Everything else — no scaffolding, no subagent, real `reads:` only, HCE
discipline — applies unchanged. `/lint` flags children older than 7
days with no `/implement` run.

## Notes

- If the context gathered in step 2 is too thin to ground a falsifiable
  hypothesis, say so in plain English and stop — better to abort than
  to fabricate rationale.
- Proposals are cheap. If you have two competing ideas, emit two
  separate proposals rather than hedging inside one.
