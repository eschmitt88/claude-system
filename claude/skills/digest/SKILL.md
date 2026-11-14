---
name: digest
description: Scheduled literature sweep. /digest searches for items newer than _meta/last_digest on the project's active themes and writes a candidates file. In agency max repos it also fetches and ingests the top candidates while the headroom verdict permits.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# digest

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

The unattended counterpart to `/discover`: no topic argument, it works out
what the project currently cares about and surfaces what is new. Built for
cron, so nobody is watching when it runs. `--dry-run` shows the queries
without writing.

## Steps

1. **Window.** Since the ISO timestamp in `_meta/last_digest`; if the file
   is missing or unparseable, the last 14 days.

2. **Themes.** Build 2–5 queries that together cover the project's current
   fronts, from `concepts/` (names and `tags:`), the last ~20 lines of
   `_meta/iteration_log.md` if present, and the tail of `NOTES.md`.

   Write each query as a 3–5 sentence scenario, the way you would brief a
   research assistant: the problem, the kind of method or result, the
   context. Keyword piles measurably degrade scientific retrieval;
   scenario queries reach evidence that lives in appendices and ablations
   (AutoResearchBench; hub concept `web-grounded-literature`).

3. **Search**, keep what falls inside the window, and drop any URL already
   in `raw/_candidates/**` or `literature/**`.

4. **Write** `raw/_candidates/YYYY-MM-DD-digest.md` in `/discover`'s format,
   with `source: digest` and a `window_since:` field. A second digest on
   the same day is `-digest-2`. At most 20 entries; more means the queries
   were too broad. With nothing new, still write the file with
   `n_returned: 0`: the absence of news is signal.

5. **Record.** Overwrite `_meta/last_digest` with the current UTC ISO
   timestamp, append `YYYY-MM-DD digest n=<count> window_since=<iso>`
   to `_meta/log.md`, then commit and push those three files by path.

6. **`agency: max` only: advance the backlog.** Under `standard` (or no
   `agency:` field) stop at step 5; curation is the user's.
   - Get the verdict:
     `~/claude-system/coordinator/.venv/bin/claude-coordinator-agency --json`.
     On `hold`, stop.
   - Otherwise `/fetch-paper` then `/ingest` the highest-ranked candidates,
     these plus any older uncurated ones, as many as `agency.md`'s batch
     scale allows for the current `aggressiveness`. Skip what is already in
     the graph. Re-check the verdict every couple of items.
   - Log `YYYY-MM-DD digest-autoingest n=<k> verdict=<v>`.
   - Run `/promote-moc`. It declines by itself when nothing is ripe.
   - Close the candidates file the `/curate` way (a `## Curation` section
     with each item's disposition, then move it to
     `raw/_candidates/_done/`). If items were left un-ingested, leave the
     file in place for the next run.

## Constraints

- Never overwrite an existing candidates file.
- `literature/` and `concepts/` change only through step 6's `/ingest`.
- No retries inside the skill: a failure should show in the cron log.
