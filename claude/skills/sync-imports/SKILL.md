---
name: sync-imports
description: Records which hub concepts the active project declares, by appending idempotent used_by entries to those concept files in agentic-research. Run after editing a project's declared concepts.
---

# sync-imports

A downstream project declares the hub concepts it depends on by naming
their paths. This skill writes the other half: a `used_by:` entry on each
named concept, so the hub can see which concepts are load-bearing. The
declaration is a record, not a load. A session that needs a concept reads
it by path.

In the `agentic-research` repo itself there is nothing to do.

## Steps

1. **Find declarations** in the project's `CLAUDE.md`,
   `.claude/rules/**/*.md` and `experiments/**/CLAUDE.md`: any line naming
   `~/projects/research/agentic-research/concepts/<name>.md` (older lines
   may carry a leading `@`).

2. **For each named concept**, add to its frontmatter, unless an entry for
   this `project_slug` already exists (the first import date is kept):

   ```yaml
   used_by:
     - project_slug: <project folder name>
       imported_on: "YYYY-MM-DD"
   ```

   - A concept with `status: retired` still gets the entry, with a
     one-line warning: retired-concept usage is signal for the hub.
   - A declared path that doesn't exist gets a warning and is skipped.
     Never create the file.

3. **Commit in the hub repo**, staging the changed concept files by path
   (never `git add -A`; the hub's scheduled jobs keep it dirty), and push.
   Skip the commit when nothing changed.
