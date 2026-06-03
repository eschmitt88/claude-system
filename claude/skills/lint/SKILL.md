---
name: lint
description: Knowledge-graph health check. Auto-detects project mode (research vs experiments) from filesystem shape and runs only the checks that apply. Always-on checks cover orphans, dead wikilinks, sourceless concepts, MoC candidates, stale candidates. Experiment-mode adds stale proposals, missing diagnostics, costly sessions without insight, stale expansions, unanchored claims. HCE-mode adds test/ access detection. Report-only — does not auto-fix. Hard failure on HCE-rule violations.
respects:
  - ~/.claude/rules/evaluation.md
---

# lint

Surface knowledge-graph rot and HCE-rule violations. All checks are
report-only **except** the HCE access check, which is a hard failure
that should block a chain from continuing.

## Project mode detection

Before running any check, decide the project's mode from the filesystem:

- **experiments** mode — `experiments/` exists and contains at least
  one dated folder matching `YYYY-MM-DD-*/`. (Empty `experiments/`,
  or only `experiments/_proposals/`, does NOT count.)
- **research** mode — anything else. Literature curation, concept
  building, MoC stewardship. No experiments to check against.

Then check HCE triggers (only meaningful in experiments mode):

- **hce_active** = experiments mode AND any of:
  `splits.yaml` at project root, an experiment subfolder named `test/`
  or with a `test/` symlink, or `evaluation_mode: hce` in the project
  `CLAUDE.md` / `budget.yaml`.

Report the detected mode at the top of the output so the user knows
what was skipped:

```
MODE: research   (no experiments/YYYY-MM-DD-*/ folders detected)
```
or
```
MODE: experiments (hce_active=true)
```

## Always-on checks (both modes)

### 1. Orphan literature notes

Files under `literature/**/*.md` with **no engagement** anywhere in
the knowledge graph. A note counts as engaged if **any** of:

- frontmatter `related_experiments:` is non-empty;
- frontmatter `related_concepts:` is non-empty;
- the `## Follow-up` section has at least one non-placeholder bullet
  (placeholder = literal `- ...` left from the template);
- the note's path appears as a `[[literature/papers/<slug>]]` link
  inside any `concepts/*.md` or `mocs/*.md` body;
- the note's slug appears in any `concepts/*.md` frontmatter
  `sources:` or `source_papers:` list.

Suggestion: either link the note into the graph or lower `relevance:`
to 1.

### 2. High-relevance papers with no follow-up

Literature notes with `relevance >= 4` and no engagement by the
definition above. These are the highest-leverage items to act on.

In **experiments mode**, also flag notes where engagement exists only
via concepts/MoCs but `related_experiments:` is empty — the paper is
in the graph but hasn't shaped a run.

### 3. Dead wikilinks

Any `[[target]]` or `[[target|alias]]` reference whose target file
does not exist anywhere under the project. Print referencing file and
line number.

### 4. Concepts without sources

Files under `concepts/*.md` whose frontmatter `sources:` list is
empty AND whose `source_papers:` list is also empty. These are claims
with no provenance — either attach sources or demote to `status: seedling`
if already mature.

### 5. MoC candidates

Clusters of ≥5 concepts sharing a tag where no `mocs/<tag>.md` exists
yet, and whose concepts are not already covered by an existing MoC.
Suggest creating the MoC with `/promote-moc <theme>`. (In `agency: max`
repos `/digest` already runs `/promote-moc` after each ingest burst, so
this check is mostly a backstop there; in `standard` repos it's the
prompt for the user to promote by hand.)

### 6. Stale candidates

Files **directly** under `raw/_candidates/` (not the `_done/` archive)
older than **14 days**. `/discover` or `/digest` found these items and
the user never curated them. Suggestion: run `/curate` (which ingests the
keepers, records declines with reasons, and moves the file to
`raw/_candidates/_done/`). A file under `_done/` is resolved and not
counted here.

### 7. High-relevance literature stale >30d

Files under `literature/**/*.md` with `relevance >= 4`, no engagement
(definition from check 1), and an `added:` date more than **30 days**
old. Stricter cousin of check 2.

## Experiments-mode checks

Skip all of these in research mode.

### 8. Stale proposals

Files under `experiments/_proposals/*.md` (not `_done/` or `_failed/`)
whose frontmatter `status: proposed` and whose `date:` is more than
**14 days** old. Suggestion: implement, rewrite, or move to
`_proposals/_failed/` with a reason.

### 9. Experiments missing diagnostics

Files under `experiments/YYYY-MM-DD-*/README.md` where either:

- the `## Diagnostics` section is missing entirely, or
- the `intended_effect_confirmed` field is empty / still contains the
  template placeholder.

Skip experiments whose frontmatter is `status: running` and whose
`date:` is within the last 24 hours. Also surface any
`TODO: diagnostics incomplete` lines that the SessionEnd hook has
appended to `_meta/log.md`.

### 10. Costly sessions without insight

Parse `_meta/token_log.ndjson`. For every session whose
`input_tokens + output_tokens + cache_creation_tokens > 500_000`,
find the experiment(s) that session touched (match on
`_meta/status.ndjson` slug entries within the session window). If
any of those experiments has an empty / missing Diagnostics section,
surface it — significant budget was burned without producing
structured insight.

### 11. Stale expansions

Files under `experiments/_proposals/_expansions/<parent>/` older than
**7 days** where `status: proposed` and there is no corresponding
`experiments/YYYY-MM-DD-<slug>/` folder (i.e. no `/implement` run).
Suggestion: implement, move to `_failed/` with a reason, or delete.

### 12. Unanchored diagnostic claims

For every `experiments/YYYY-MM-DD-*/README.md` Diagnostics section,
check each field that asserts a concrete effect:

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

Anchor detection is lightweight regex — if the claim line has none
of the above, flag it. Motivated by Kosmos (arXiv 2511.02824):
anchors are what separate an agent's claims from hallucinated
summaries of its own work.

## HCE-mode check

Skip unless `hce_active` is true.

### 13. `test/` access during search — HARD FAILURE

Two sub-checks, either of which fails the lint:

a. **DVC deps**: parse `dvc.lock` (or `dvc.yaml` when `.lock` is
   absent) and check each stage's `deps:` list. Any stage whose name
   is not `final_eval` whose deps include a path under `test/` is a
   hard failure. The `final_eval` stage is the only permitted
   consumer of `test/` under the HCE rule
   (`~/.claude/rules/evaluation.md`).

b. **Session tool logs**: for each experiment, look for a saved
   tool-call log (`experiments/<slug>/log.md` plus any
   `_meta/status.ndjson` entries tagged to that slug) and grep for
   `Read`, `Glob`, or `Grep` calls whose path argument begins with
   `test/`. Anything found is a hard failure.

Output violations as `HCE VIOLATION (HARD)`. Do not downgrade to a
warning.

## Output format

```
MODE: research   (no experiments/YYYY-MM-DD-*/ folders detected)

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

STALE CANDIDATES (N)
  raw/_candidates/2026-03-20-retrieval.md  age=35d

HIGH-RELEVANCE LITERATURE STALE >30d (N)
  literature/papers/qux.md  relevance=5  added=2026-03-10
```

In experiments mode the report continues with stale proposals,
missing diagnostics, costly sessions, stale expansions, and
unanchored claims sections; with `hce_active`, the HCE VIOLATION
section follows.

## Notes

- Read-only. Does not modify files.
- Run weekly or before a `/wrap` at the end of a big push.
- In research-only projects, the report should be short and focus
  on knowledge-graph hygiene; if it's noisy, the broadened
  engagement definition is the lever to revisit.
- HCE violations should be treated as blocking: do not proceed with
  further `/iterate` cycles until they are resolved.
- Subagents may be useful when the literature set is large —
  delegate the scan, keep the synthesis and reporting in the main
  agent.
