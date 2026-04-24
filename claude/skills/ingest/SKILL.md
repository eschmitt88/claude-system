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

## Sub-contract: meta-project import back-reference

The `agentic-research` project at
`~/projects/research/agentic-research/` is the shared hub whose
`concepts/` directory other projects `@import` from. On every
`/ingest` invocation, detect imports and record a back-reference on
the source concept so the meta project can see which patterns are
load-bearing.

### Trigger

Scan the following files on the active project for `@import`
directives pointing at paths under
`~/projects/research/agentic-research/concepts/`:

- the project root `CLAUDE.md`;
- every file under `.claude/rules/**/*.md`;
- the file being ingested (in case a new raw source itself imports).

Resolve `~` to the invoking user's home. Skip the sub-contract
entirely when the active project *is* `agentic-research` — the meta
project does not back-reference itself.

### Action

For each unique absolute path matched, read the target concept file
and perform this append-if-missing operation on its frontmatter's
`used_by:` list:

```yaml
used_by:
  - project_slug: <active-project-slug>
    imported_on: <YYYY-MM-DD>
```

Idempotency rule: **do not add a duplicate entry for the same
`project_slug`**. If an entry already exists with that slug, leave
the list untouched — regardless of whether the `imported_on` date
differs. The first import timestamp is the one we keep; later imports
confirm continued use but do not overwrite history.

If `used_by:` is absent or not a list, initialize it as a list with
the single entry above.

### Retired-status warning

Before writing, read the target concept's `status:` field. If
`status: retired`, emit a one-line warning to the user on the
downstream side ("WARNING: importing retired concept <name>; see
<concept-path> for what replaces it") but still perform the append.
The import is allowed — the back-reference is still useful to the
meta project as signal that someone is hanging on to a retired
pattern — but the user should be told.

### Target-missing handling

If an `@import` points at a path under the meta-project concepts
directory that does not exist, emit a one-line warning ("WARNING:
@import target <path> not found") and skip the append for that
target. Do not fabricate the target file. Do not abort the ingest.

### Inclusion in the diff batch

Any concept-file modifications produced by this sub-contract are
shown in the same diff batch as the literature-note and local-concept
changes in step 8. The user confirms once; all files are written on
confirmation or none on refusal.

## Notes

- Never modify `raw/` itself. Treat it as read-only.
- If the file under `raw/` is empty or unreadable, abort and tell the user.
- The cross-project sub-contract runs even when the primary ingest
  has no concept updates of its own (e.g. re-ingesting an existing
  raw file to pick up a new `@import` in CLAUDE.md). In that case,
  the diff batch contains only meta-project concept updates plus a
  log line.
