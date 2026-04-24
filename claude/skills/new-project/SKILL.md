---
name: new-project
description: Scaffold a new research project at ~/projects/research/<slug> from the user template. Copies ~/.claude/templates/project/, runs git init, dvc init, uv init, and creates the initial commit. Use when the user runs /new-project <slug>.
---

# new-project

Scaffold a new research project.

## Arguments

- `<slug>` — the project folder name. Required. Kebab-case; `_scratch` is
  allowed as a sandbox slug.

## Steps

1. **Validate**: refuse if `~/projects/research/<slug>` already exists.
   Refuse if the slug contains `/`, whitespace, or path escapes.

2. **Copy the template**:

   ```sh
   cp -a ~/.claude/templates/project/ ~/projects/research/<slug>/
   ```

   Preserve the hidden `.claude/` and `.gitignore` in the copy. Use
   `cp -a` (archive) so modes and the dot-dirs come with.

3. **Substitute template tokens**: replace `{{PROJECT_SLUG}}` in `README.md`
   and `CLAUDE.md` with the real slug.

4. **Initialize tools** (from inside the new project dir):

   ```sh
   git init -q -b main
   dvc init -q
   # uv init rejects slugs that don't parse as a Python package name
   # (e.g. leading underscores). Derive a valid --name from the slug:
   PKG="$(printf '%s' "$SLUG" | sed 's/^[^a-zA-Z0-9]*//' | tr '[:upper:]' '[:lower:]')"
   [ -z "$PKG" ] && PKG=project
   uv init --bare --no-workspace --no-pin-python --name "$PKG"
   ```

   `uv init` drops a `pyproject.toml`. Leave `.python-version`
   untouched if uv creates one.

5. **Initial commit**:

   ```sh
   git add -A
   git commit -q -m "scaffold: initial skeleton for <slug>"
   ```

6. **Create a private GitHub remote and push** (best-effort — this
   step must not fail the skill):

   ```sh
   if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
     if gh repo create --private --source . --push "$SLUG" 2>/tmp/gh-err; then
       echo "Created github:$(gh api user --jq .login)/$SLUG"
     else
       echo "gh repo create failed (continuing without remote):"
       cat /tmp/gh-err
     fi
   else
     echo "gh not available or not authenticated — skipping remote creation."
   fi
   ```

   Common skip cases: `gh` not installed, not authenticated, or a
   repo of that name already exists on the user's account. In all of
   these, emit a one-line warning and continue — the skill must not
   fail because a remote couldn't be created.

7. **Sync imports**: if the scaffolded `CLAUDE.md` contains any
   `@import` lines pointing at
   `~/projects/research/agentic-research/concepts/`, run
   `/sync-imports` so the meta project's concept files gain their
   `used_by:` back-references immediately. This was previously
   deferred until the first `/ingest`; running it here fixes Phase 5
   bug 9 (back-references were invisible until a raw file was
   ingested).

8. **Report**: print the resulting tree (depth 2) and the slug's absolute
   path so the user knows where work lives. If a remote was created,
   print its URL.

## Notes

- All artifacts land on the SN850X via `~/projects/` — never inside `~/`.
- Remote creation is best-effort: projects without a GitHub remote still
  work locally. Re-run `gh repo create --private --source . --push` by
  hand later if the skill skipped it.
- If any step fails, leave the half-scaffolded directory in place and
  report which step failed — don't auto-rollback.
