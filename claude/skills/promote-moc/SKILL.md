---
name: promote-moc
description: Promote a ripe cluster of related concepts into a Map of Content at mocs/<theme>.md. Detects clusters of >=5 related concepts on a theme that are not already substantially covered by an existing MoC, then synthesizes the MoC (framing + layered organization + concept wikilinks) from the concept files. In standard repos it proposes and waits; in `agency: max` repos it creates, commits, and pushes autonomously. This is the "act on it" counterpart to /lint's MoC-candidate detection.
respects:
  - ~/claude-system/claude/rules/agency.md
---

# promote-moc

Turn an accumulating cluster of concepts into a navigable Map of Content.
The framework's rule (user `CLAUDE.md`): "when >=5 related concepts
accumulate on a theme, promote them to a `mocs/<theme>.md`." `/lint`
*detects* ripe clusters; this skill *creates* the MoC.

## Arguments

- `<theme>` — optional. Force-promote a specific theme/tag (e.g.
  `/promote-moc agent-memory`). With no argument, auto-detect the ripest
  cluster and promote it (or report that none is ripe).

## Ripeness — when to promote (and when NOT to)

A cluster is **ripe** only when BOTH hold:

1. **>=5 related concepts.** Group `concepts/*.md` by shared `tags:` (merge
   near-synonym tags with judgment — e.g. `memory` + `procedural-memory`).
   The cluster is the set of concepts on one coherent theme.
2. **Not already mapped.** No existing `mocs/*.md` already covers a
   majority (>= half) of the cluster's concepts. A new MoC that would
   duplicate an existing one is **not** ripe — prefer updating the
   existing MoC's `concepts:` and sources instead, or splitting it only
   when the sub-theme has clearly outgrown the parent.

If nothing is ripe, say so and stop. Do **not** manufacture a thin or
redundant MoC to have something to do — a 3-concept "cluster", or one
whose concepts already live in another MoC, stays un-promoted. This
restraint is the point: the value is in real structure, not MoC count.

## Steps

1. **Refuse if the active project has no `concepts/`.**

2. **Detect** per the ripeness test above. List every candidate cluster
   with its concept count and overlap with existing MoCs, then pick the
   ripest un-mapped one (or the `<theme>` argument if given). Report what
   you found, including clusters you are **declining** and why.

3. **Synthesize `mocs/<theme>.md`** — match the structure of any existing
   `mocs/*.md` in the project (read one first). Minimum shape:
   - Frontmatter: `kind: moc`, `name`, `status: active`, `added: <today>`,
     a `concepts:` list of `[[concepts/<slug>]]` wikilinks, and `tags:`
     including `moc` + the theme.
   - A framing paragraph: what question this theme answers and why these
     concepts belong together.
   - A layered/grouped organization: 2-4 subsections that each group a
     few concepts by role, each concept introduced with a one-line job
     and its `[[concepts/<slug>]]` link. Cite the key `[[literature/...]]`
     sources that anchor the theme.
   - A short "open thread / hypothesis" close if one is evident.

4. **Backlink** (lightweight): add the MoC to each member concept's
   frontmatter — if concepts carry a `mocs:` field append `[[mocs/<theme>]]`;
   otherwise skip rather than invent a schema.

5. **Update** `_meta/index.md` (list the new MoC) and append to
   `_meta/log.md`: `YYYY-MM-DD HH:MM promote-moc <theme> (<N> concepts)`.

6. **Persist** per `~/claude-system/claude/rules/agency.md`:
   - **`agency: standard`** — show the diff and wait for confirmation.
   - **`agency: max`** — write, then `git add -A && git commit && git push`
     (so the Pages site updates). Commit message:
     `promote-moc YYYY-MM-DD: <theme> (<N> concepts)`.

## Notes

- Read-then-write: synthesize from the actual concept files, not memory.
  Every concept in the `concepts:` list must exist.
- Promotion is reversible (`git revert`); subsumption mistakes are not
  free to a reader, so bias toward updating an existing MoC over spawning
  an overlapping one.
- Pairs with `/lint` (detects candidates) and `/digest` (in `agency: max`
  repos, runs this after an ingest burst to keep the graph navigable).
