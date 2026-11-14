---
name: curate
description: Close candidate files in raw/_candidates/. Each item is ingested (fetch-paper + ingest) or declined with a recorded reason, then the file is archived to _done/. Proposes and waits in standard repos; acts unasked in agency max repos.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# curate

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

`/discover` and `/digest` open candidate files; this closes them. A file is
**uncurated** while it sits directly in `raw/_candidates/`. Moving it to
`raw/_candidates/_done/` is what resolves it for the dashboard, the Pages
viewer and `/lint`.

`/curate [file]`: one file, or with no argument every uncurated file,
oldest first.

## For each file

1. **Dedup.** An item whose URL is already in `literature/**` (`source:` /
   `url:`) is already curated. Record it as such; don't re-ingest.

2. **Give every remaining item a disposition.**
   - **ingest**: on-mission and substantive. Run `/fetch-paper`, then
     `/ingest`. An entry marked `verified: snippet`, or with no `verified:`
     field, was never read by `/discover`: check that the fetched source is
     the work the entry describes, and note any wrong ID or number.
   - **decline**: a duplicate, a thin hot-take, link-rot, off-mission, or
     legally fraught. Give a one-line reason. Never drop an item silently;
     a decline with a reason is a reviewable decision.

   Declining most of a weak file is correct. The goal is a recorded
   disposition for every item, not maximum ingestion.

   Under `agency: standard`, propose the dispositions and wait. Under
   `max`, act, gated by the headroom verdict (`agency.md`).

3. **Record.** Append a `## Curation` section listing each item as
   `ingested → <citekey>`, `already in graph`, or `declined — <reason>`,
   and add `curated: <today>` to the frontmatter.

4. **Archive** the file to `raw/_candidates/_done/<same-name>`.

5. **Log** `YYYY-MM-DD curate <file> ingested=<k> declined=<j> dup=<d>`
   in `_meta/log.md`, then commit and push by path, once per file, so the
   uncurated count drops as you go. Re-check the verdict between files and
   stop on `hold`.

After a batch that added or linked concepts, run `/promote-moc`.
