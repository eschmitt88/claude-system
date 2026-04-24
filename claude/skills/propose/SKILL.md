---
name: propose
description: Strategic ideation for the active research project — no implementation. Reads concepts/, the 10 most recently modified literature notes, and the 5 most recent experiment READMEs + their metrics.json. Emits one proposal file at experiments/_proposals/YYYY-MM-DD-<slug>.md with flat YAML frontmatter (hypothesis, rationale, reads, expected_metric, design_sketch, risks, related_prior, estimated_runtime, status) plus a prose argument. Does not scaffold an experiment, write code, or touch dvc.yaml.
respects:
  - ~/.claude/rules/evaluation.md
---

# propose

Produce a single experiment proposal. This is the ideation half of the
MLE-IDEATOR split: **no code, no scaffolding, no dvc.yaml edits**. The
output is a decision document.

## Arguments

- `[<concept-or-moc>]` — optional. A concept name, MoC name, or path under
  `concepts/` or `mocs/`. If present, the proposal focuses on that theme.
  If absent, synthesize from the active `NOTES.md` tail.

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

## Notes

- If the context gathered in step 2 is too thin to ground a falsifiable
  hypothesis, say so in plain English and stop — better to abort than
  to fabricate rationale.
- Proposals are cheap. If you have two competing ideas, emit two
  separate proposals rather than hedging inside one.
