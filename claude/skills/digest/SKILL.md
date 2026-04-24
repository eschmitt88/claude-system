---
name: digest
description: /digest runs a web sweep for fresh items related to the project's active concepts and recent iterations since the last digest timestamp in _meta/last_digest, and drops new candidates into raw/_candidates/. Designed for invocation by cron or the schedule skill. Updates _meta/last_digest on completion. Never auto-ingests — user curates.
respects:
  - ~/.claude/rules/evaluation.md
---

# digest

Periodic, low-touch literature sweep. Where `/discover <topic>` is
user-initiated and focused, `/digest` is autonomous and broad — it
re-reads the project's current direction and surfaces what's new
since last time.

Intended to be called by the `schedule` skill or a cron job (e.g.
daily or weekly). The user is not in the loop when it fires, so the
skill is conservative: it never ingests, never writes to `literature/`
or `concepts/`, and never overwrites existing candidate files.

## Arguments

None (or an optional `--dry-run` the caller can pass to inspect what
would be searched without writing).

## Steps

1. **Locate the active project.** Refuse if none.

2. **Determine the window.** Read `_meta/last_digest`:
   - If the file exists and contains a parseable ISO timestamp, the
     window is "since that timestamp".
   - Otherwise default to the last 14 days.

3. **Gather the active themes** — do not search on the raw argument
   (there is none). Instead, synthesize queries from:
   - `concepts/` filenames + their `tags:` frontmatter;
   - the last ~20 entries in `_meta/iteration_log.md` (if present);
   - the last 50 lines of `NOTES.md`.

   Pick 2–5 queries that together cover the project's current fronts.
   Use your judgment on how to split — one per active theme is a
   good default.

4. **Run each query** via `WebSearch`, filter on recency inside the
   window. Deduplicate against URLs already present in
   `raw/_candidates/**/*.md` and `literature/**/*.md` (read the files
   and grep for the URL). Skip items already in the knowledge graph.

5. **Write a single candidates file** at
   `raw/_candidates/YYYY-MM-DD-digest.md` with the same structure as
   `/discover` produces, but frontmatter marked `source: digest` and
   including a `window_since:` field.

   If two digests run on the same day, append a disambiguator
   (`-digest-2`, `-digest-3`).

6. **Update `_meta/last_digest`** with the current ISO timestamp
   (UTC). One line, overwrite.

7. **Append to `_meta/log.md`**:
   `YYYY-MM-DD HH:MM digest n=<count> window_since=<iso>`.

## Constraints

- Do not invoke `/ingest` or `/fetch-paper` automatically. Curation
  is the user's job.
- Do not modify `concepts/` or `literature/`.
- If no new items pass the filter, still update `_meta/last_digest`
  and write a candidates file with `n_returned: 0` — the absence of
  news is signal.
- Hard cap: 20 items per digest file. More than that means the queries
  are too broad; narrow them on the next call.

## Notes

- This skill is designed for cron. If it errors, the caller will see
  it in the cron log; do not retry inside the skill.
- Pair with `/lint` — which flags stale candidates files — so the
  user sees when they've fallen behind curating.
