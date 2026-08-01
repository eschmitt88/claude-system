---
name: sync-imports
description: Scan the active project for @import directives pointing at agentic-research/concepts/ and append idempotent used_by: back-references to each target concept file. Standalone skill factored out of /ingest so it can run independent of any raw/ file. /ingest and /new-project both call it.
---

# sync-imports

Record cross-project concept imports as `used_by:` back-references on
the meta-project side (`~/projects/research/agentic-research/concepts/`).

This was previously a sub-contract buried inside `/ingest`, which meant
it only ran when a new raw file was ingested. Factoring it out means
any project (even one that never ingests raw material) can register
its imports the moment they're added to CLAUDE.md.

## Arguments

None. Operates on the active project.

## When to use

- **Automatically**: `/ingest` calls `/sync-imports` before showing its
  diff batch; `/new-project` calls it right after scaffolding so the
  inherited imports register immediately.
- **Manually**: after editing a project's `CLAUDE.md` to add a new
  `@import` line — before starting a session that relies on the
  back-reference being present on the meta side.

## Skip condition

If the active project **is** `agentic-research` itself, exit 0 with no
action. The meta project doesn't back-reference itself.

## Steps

1. **Refuse if the cwd is not inside a project.**

2. **Skip self-reference**: if the project basename is
   `agentic-research`, exit 0 with a one-line message.

3. **Scan for `@import` directives**. Files to search:
   - the project root `CLAUDE.md`;
   - every file under `.claude/rules/**/*.md`;
   - every file under `experiments/**/CLAUDE.md` (experiment-level
     imports exist too and count).

   Match lines of the form:
   ```
   @import ~/projects/research/agentic-research/concepts/<name>.md
   ```
   Expand `~` to the user's home. Deduplicate absolute paths.

4. **For each matched path**, append an idempotent entry to the
   target concept file's `used_by:` frontmatter list:

   ```yaml
   used_by:
     - project_slug: <active-project-basename>
       imported_on: <today's date, YYYY-MM-DD>
   ```

   **Idempotency rule**: do not add a duplicate entry for the same
   `project_slug`. If one exists with that slug, leave the list
   untouched regardless of whether the `imported_on` date differs.
   The first import date is what we keep.

   If `used_by:` is absent or not a list, initialize it as a list
   with the single entry above.

5. **Retired-status warning**: read each target concept's `status:`.
   If `status: retired`, emit a one-line warning
   ("WARNING: importing retired concept <name>; see <path> for what
   replaces it") but still perform the append. Tracking retired-concept
   usage is signal to the meta project.

6. **Target-missing handling**: if an `@import` points at a path that
   doesn't exist, emit a one-line warning ("WARNING: @import target
   <path> not found") and skip the append. Do not fabricate the file.

7. **Write the back-references** — an artifact write (bookkeeping, not
   hypothesis selection), so no confirmation gate; show the diff of
   what changed. When called by `/ingest` or `/new-project`, the parent
   skill batches these into its own diff.

## Notes

- This skill **modifies files outside the active project**. That's
  unusual and deliberate — it's the one skill whose job is to update
  the meta project from downstream signals.
- The `/ingest` skill calls `/sync-imports` as part of its diff batch
  (step 7 of `/ingest`). `/new-project` calls it right after the
  initial commit so back-references land immediately.
- Long-term, consider running `/sync-imports` from a PostToolUse hook
  on CLAUDE.md edits. Not worth the complexity until it's proven
  useful.
