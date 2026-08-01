---
name: curate
description: Resolve uncurated candidate files in raw/_candidates/. For each item, decide ingest vs decline; ingest the keepers (fetch-paper + ingest), record a one-line reason for declines, append a ## Curation summary, then move the file to raw/_candidates/_done/ so it stops counting as uncurated. In standard repos it proposes the dispositions and waits; in `agency: max` repos it acts autonomously while the headroom verdict permits. Closes the loop /discover and /digest open.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# curate

`/discover` and `/digest` *open* candidate files in `raw/_candidates/`;
nothing *closes* them, so they accumulate and read as "uncurated" forever.
This skill is the close: review each item, act, and archive the file.

A candidate file is **uncurated** when it sits directly in
`raw/_candidates/` (not under `raw/_candidates/_done/`). That subfolder is
the archive — moving a fully-processed file there is what drops it from the
uncurated count (the dashboard, the Pages viewer, and `/lint` all treat
`_done/` as resolved).

## Arguments

- `[file]` — optional. Curate one candidate file. With no argument, curate
  every uncurated file, oldest first.

## Steps

For each uncurated candidate file:

1. **Dedup.** Extract each item's URL and check it against the graph
   (`literature/**` notes and their `source:`/`url:` fields). Items already
   in the graph are **already curated** — record them as such, don't
   re-ingest.

2. **Decide a disposition per remaining item:**
   - **ingest** — on-mission and substantive (a paper, a real repo, a
     load-bearing post). Run `/fetch-paper` then `/ingest` (which fills the
     trust-signal frontmatter). Under `agency: max`, do this autonomously,
     gated by the headroom verdict (`claude-coordinator-agency`); under
     `standard`, propose the list and wait.
   - **decline** — a duplicate, a thin hot-take, link-rot, off-mission, or
     legally fraught (e.g. a DMCA'd repo). Record a one-line reason. Do
     **not** silently drop items — a decline with a reason is a real,
     reviewable curation decision.

3. **Append a `## Curation` section** to the file recording every item's
   disposition: `ingested → <citekey>`, `already in graph`, or
   `declined — <reason>`. Add `curated: <today>` to the frontmatter.

4. **Archive**: move the file to `raw/_candidates/_done/<same-name>`.

5. **Log**: append to `_meta/log.md`:
   `YYYY-MM-DD HH:MM curate <file> ingested=<k> declined=<j> dup=<d>`.

6. **Persist** per `~/claude-system/claude/rules/agency.md`: commit and (in `max` repos)
   push after each file, so the uncurated count visibly drops on the Pages
   site. Re-check the headroom verdict between files; stop on `hold`.

## Constraints

- HCE: never touch `test/` (see `evaluation.md`).
- Quality over completeness: it is correct to decline most of a low-value
  file and archive it — the goal is that every item has a recorded
  disposition and the file leaves the uncurated pile, not that everything
  gets ingested.
- After ingesting a batch, run `/promote-moc` (a freshly-linked concept may
  tip a theme to ripe).

## Notes

- `/digest` step 8 archives its own file via this same lifecycle after its
  auto-advance; `/curate` is for the standing backlog and for `/discover`
  output.
- Pairs with `/lint`'s stale-candidates check, which now only counts files
  outside `_done/`.
