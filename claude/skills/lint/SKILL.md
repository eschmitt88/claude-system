---
name: lint
description: Weekly knowledge-graph health check. Surfaces orphan literature notes, high-relevance papers without follow-up, dead wikilinks, concepts without sources, stale proposals, experiments missing diagnostics, costly sessions without insight, stale candidates/expansions, unanchored diagnostic claims, and any test/ access during the search phase. Report-only — does not auto-fix. Hard failure on HCE-rule violations.
respects:
  - ~/.claude/rules/evaluation.md
---

# lint

Surface knowledge-graph rot and HCE-rule violations. All checks are
report-only **except** #12 (test/ access during search), which is a
hard failure that should block a chain from continuing.

## Checks

Run each check over the active project and print a short report grouped
by category. Do not auto-fix — the user decides what to clean up.

### 1. Orphan literature notes

Files under `literature/**/*.md` whose frontmatter `related_experiments:`
list is empty or missing. Suggestion: either link to an experiment or
lower `relevance:` to 1.

### 2. High-relevance papers with no follow-up

Literature notes with `relevance >= 4` and an empty `## Follow-up` section
(or no follow-up bullets). These are the highest-leverage items to act on.

### 3. Dead wikilinks

Any `[[target]]` or `[[target|alias]]` reference whose target file does
not exist anywhere under the project. Print the referencing file and
line number.

### 4. Concepts with no sources

Files under `concepts/*.md` whose frontmatter `sources:` list is empty.
These are claims with no provenance — either attach sources or demote to
`status: seedling` if already mature.

### 5. MoC candidates

Clusters of ≥5 concepts sharing a tag where no `mocs/<tag>.md` exists yet.
Suggest creating the MoC.

### 6. Stale proposals

Files under `experiments/_proposals/*.md` (not `_done/` or `_failed/`)
whose frontmatter `status: proposed` and whose `date:` is more than
**14 days** old. Suggestion: implement, rewrite, or move to
`_proposals/_failed/` with a reason.

### 7. Experiments missing diagnostics

Files under `experiments/*/README.md` where either:

- the `## Diagnostics` section is missing entirely, or
- the `intended_effect_confirmed` field is empty / still contains the
  template placeholder (`<yes | no | partial>` or similar).

Skip experiments whose frontmatter is `status: running` and whose
`date:` is within the last 24 hours. Also surface any
`TODO: diagnostics incomplete` lines that the SessionEnd hook has
appended to `_meta/log.md`.

### 8. High-relevance literature with no follow-up after 30 days

Files under `literature/**/*.md` with `relevance >= 4`, an empty
`related_experiments:` list, and an `added:` date more than **30 days**
old. Stricter cousin of check #1.

### 9. Costly sessions without insight

Parse `_meta/token_log.ndjson`. For every session whose
`input_tokens + output_tokens + cache_creation_tokens > 500_000`, find
the experiment(s) that session touched (match on
`_meta/status.ndjson` slug entries within the session window, or fall
back to the session's tool-call log if available). If any of those
experiments has an empty / missing Diagnostics section, surface it —
significant budget was burned without producing structured insight.

### 10. Stale candidates

Files under `raw/_candidates/` older than **14 days**. `/discover` or
`/digest` found these items and the user never curated them.
Suggestion: `/fetch-paper` the entries worth keeping, delete the file,
or re-run `/discover` to refresh.

### 11. Stale expansions

Files under `experiments/_proposals/_expansions/<parent>/` older than
**7 days** where `status: proposed` and there is no corresponding
`experiments/YYYY-MM-DD-<slug>/` folder (i.e. no `/implement` run).
Suggestion: implement, move to `_failed/` with a reason, or delete.

### 12. Unanchored diagnostic claims

For every `experiments/*/README.md` Diagnostics section, check each
field that asserts a concrete effect:

- `intended_effect_confirmed: yes` or `partial`
- `delta_from_prior` with a numeric metric delta
- `unexpected_findings` with a non-"none" value

For each such claim, require a **citation anchor** — any of:

- a fenced or inline code reference like `train.py:42-58` or
  `src/model.py:loss_fn`
- a metrics pointer like `metrics.json:val_acc` or
  `results/per_seed.json`
- a `[[literature/...]]` or `[[concepts/...]]` wikilink
- a `notes.qmd:cell-label` reference

Anchor detection is lightweight regex — if the claim line has none of
the above, flag it. Motivated by Kosmos (arXiv 2511.02824): anchors are
what separate an agent's claims from hallucinated summaries of its own
work.

### 13. `test/` access during search — HARD FAILURE

Two sub-checks, either of which fails the lint:

a. **DVC deps**: parse `dvc.lock` (or `dvc.yaml` when `.lock` is
   absent) and check each stage's `deps:` list. Any stage whose name
   is not `final_eval` whose deps include a path under `test/` is a
   hard failure. The `final_eval` stage is the only permitted
   consumer of `test/` under the HCE rule
   (`~/.claude/rules/evaluation.md`).

b. **Session tool logs**: for each experiment, look for a saved tool-call
   log (`experiments/<slug>/log.md` plus any `_meta/status.ndjson`
   entries tagged to that slug) and grep for `Read`, `Glob`, or `Grep`
   calls whose path argument begins with `test/`. Anything found is a
   hard failure.

Output violations as `HCE VIOLATION (HARD)`. Do not downgrade to a
warning.

## Output format

```
ORPHANS (N)
  literature/papers/foo.md

HIGH-RELEVANCE NO FOLLOWUP (N)
  literature/papers/bar.md  relevance=5

DEAD WIKILINKS (N)
  literature/papers/baz.md:42  [[missing-concept]]

CONCEPTS WITHOUT SOURCES (N)
  concepts/thing.md

MoC CANDIDATES (N)
  tag=embeddings (7 concepts) — suggest mocs/embeddings.md

STALE PROPOSALS (N)
  experiments/_proposals/2026-03-30-foo.md  age=22d

MISSING DIAGNOSTICS (N)
  experiments/2026-04-10-bar/README.md  no ## Diagnostics section

HIGH-RELEVANCE LITERATURE STALE >30d (N)
  literature/papers/qux.md  relevance=5  added=2026-03-10

COSTLY SESSIONS WITHOUT INSIGHT (N)
  session=abc123 tokens=712_450 touched=experiments/2026-04-18-foo/ — no Diagnostics

STALE CANDIDATES (N)
  raw/_candidates/2026-03-20-retrieval.md  age=35d

STALE EXPANSIONS (N)
  experiments/_proposals/_expansions/ema-downweight/variant-a.md  age=9d (no /implement)

UNANCHORED DIAGNOSTIC CLAIMS (N)
  experiments/2026-04-18-foo/README.md:62  intended_effect_confirmed: yes — <no anchor>

HCE VIOLATION (HARD) (N)
  experiments/2026-04-20-bar/dvc.lock  stage=eval deps include test/targets.parquet
  experiments/2026-04-19-baz/log.md  Read test/labels.json during search phase
```

## Notes

- Read-only. Does not modify files.
- Run weekly or before a `/wrap` at the end of a big push.
- HCE violations should be treated as blocking: do not proceed with
  further `/iterate` cycles until they are resolved.
- Subagents may be useful when the literature set is large — delegate
  the scan, keep the synthesis and reporting in the main agent.
