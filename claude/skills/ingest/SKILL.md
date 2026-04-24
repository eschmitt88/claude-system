---
name: ingest
description: Ingest a file in raw/ into the knowledge graph. Proposes a literature/<kind>/<filename>.md from the matching _meta/templates/ template, identifies candidate concepts (updates existing or seeds new), updates index + log, shows diff.
---

# ingest

Turn a raw source into a processed literature note and seed any concepts
it raises.

## Arguments

- `<path>` — path to the file under `raw/`. Required.

## Steps

1. **Classify the kind**: infer from the path.
   - `raw/papers/*` → `paper`
   - `raw/repos/*` → `repo`
   - `raw/web/*`   → `post`
   Override if the content clearly disagrees.

2. **Read the raw source**. For PDFs, extract enough to fill TL;DR, claims,
   methods, results. For repos, scan README + top-level layout. For posts,
   read the whole thing.

3. **Propose the processed note** at
   `literature/<kind>s/<safe-filename>.md` using the matching template
   from `_meta/templates/<kind>.md`. Pre-fill:
   - `source:` → the raw path.
   - `added:` → today's date.
   - `title`/`name`, `authors`, `year`, `venue`, `url` where visible.
   - `relevance:` left at 0 for the user to set.
   - `tags:` suggested from content; user can prune.

4. **Candidate concepts**: extract 1–5 atomic ideas the source raises.
   For each, check `concepts/` for an existing file by name (case- and
   punctuation-insensitive match). If it exists, propose adding the
   literature note to its `sources:`. Otherwise propose a new seedling
   concept file from `_meta/templates/concept.md`.

5. **Update `_meta/index.md`** if a new MoC candidate is emerging
   (≥5 concepts in a cluster).

6. **Append to `_meta/log.md`**: `YYYY-MM-DD HH:MM ingest <raw-path>`.

7. **Cross-project import back-reference** (see sub-contract below).
   Run once per `/ingest` invocation, before the diff is shown, so any
   changes to meta-project concept files are part of the same
   confirmation batch.

8. **Show the diff** for every file proposed/modified and wait for
   confirmation.

## Cross-project import back-reference — call `/sync-imports`

The back-reference append logic (scan `@import` directives → append
idempotent `used_by:` entries on the meta side) lives in the
dedicated `/sync-imports` skill. `/ingest` calls it as part of step
7 so any concept-file modifications land in the same diff batch as
the literature-note and local-concept changes.

Specifically: in step 7, invoke `/sync-imports` on the active project
before showing the diff. Any concept-file modifications it produces
are added to the batch and the user confirms once; all files are
written on confirmation or none on refusal.

This was previously an inline sub-contract inside `/ingest`, which
meant the back-reference only ran when ingesting a raw file.
Factoring it out (Phase 6 bug 9) lets any project invoke it
independently — useful for `/new-project` and for manual re-runs
after editing `CLAUDE.md`.

## Notes

- Never modify `raw/` itself. Treat it as read-only.
- If the file under `raw/` is empty or unreadable, abort and tell the user.
- The cross-project sub-contract runs even when the primary ingest
  has no concept updates of its own (e.g. re-ingesting an existing
  raw file to pick up a new `@import` in CLAUDE.md). In that case,
  the diff batch contains only meta-project concept updates plus a
  log line.
