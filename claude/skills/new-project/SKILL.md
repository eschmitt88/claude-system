---
name: new-project
description: Scaffold a new research project at ~/projects/research/<slug> from the user template. Copies ~/.claude/templates/project/, runs git init, dvc init, uv init, creates the initial commit, creates a GitHub remote (public by default), and enables a zero-build GitHub Pages site from docs/. Use when the user runs /new-project <slug>.
---

# new-project

Scaffold a new research project.

## Arguments

- `<slug>` — the project folder name. Required. Kebab-case; `_scratch` is
  allowed as a sandbox slug.
- `--private` — create the GitHub remote private instead of public.
  Default is **public** so the repo gets a standalone GitHub Pages site
  (GitHub Pages on a private repo needs a paid plan). Pass `--private`
  when the work must not be public; the Pages step is then skipped with
  a note.
- `--experiments` — this project will run experiments: link the
  experiment-loop skill group (`/propose`, `/implement`, `/iterate`,
  `/new-experiment`, `/derive-experiment`) into the project. If the
  user's request makes the project's shape obvious (e.g. "a project to
  train X" vs "a lit review of Y"), infer this flag rather than asking.
  Lit/web-research-only projects omit it and stay lean; they can
  graduate later (see "Growing a lit repo into an experimenting one"
  in the claude-system README).

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

   With `--experiments`, also link the experiment-loop skill group so
   it lands in the initial commit:

   ```sh
   ln -s ~/claude-system/claude/skills-experiment .claude/skills
   ```

5. **Initial commit**:

   ```sh
   git add -A
   git commit -q -m "scaffold: initial skeleton for <slug>"
   ```

6. **Create the GitHub remote and push** (best-effort — this step must
   not fail the skill). Public by default; `--private` flips it:

   ```sh
   VIS=public; [ "$PRIVATE" = 1 ] && VIS=private
   if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
     if gh repo create --"$VIS" --source . --push "$SLUG" 2>/tmp/gh-err; then
       OWNER="$(gh api user --jq .login)"
       echo "Created github:$OWNER/$SLUG ($VIS)"
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

7. **Enable the GitHub Pages site** (only when the remote was created
   **public** — Pages on a private repo needs a paid plan). The
   template already ships `docs/index.html`, a zero-build viewer that
   auto-detects owner/repo from the Pages URL and renders the repo's
   `literature/ concepts/ mocs/ experiments/` structure live. Just
   enable Pages from the `/docs` folder:

   ```sh
   if [ "$VIS" = public ] && [ -n "${OWNER:-}" ]; then
     if gh api -X POST "repos/$OWNER/$SLUG/pages" \
          -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1; then
       echo "Pages enabled → https://$OWNER.github.io/$SLUG/ (first build ~1-2 min)"
     else
       echo "Pages enable skipped (already enabled, or insufficient scope)."
     fi
   else
     echo "Pages skipped — repo is private (needs a public repo or paid plan)."
   fi
   ```

   Nothing else is required: the viewer needs no build step and no
   regeneration. It reads the live file tree on each page load.

8. **Sync imports**: if the scaffolded `CLAUDE.md` contains any
   `@import` lines pointing at
   `~/projects/research/agentic-research/concepts/`, run
   `/sync-imports` so the meta project's concept files gain their
   `used_by:` back-references immediately. This was previously
   deferred until the first `/ingest`; running it here fixes Phase 5
   bug 9 (back-references were invisible until a raw file was
   ingested).

9. **Report**: print the resulting tree (depth 2) and the slug's absolute
   path so the user knows where work lives. If a remote was created,
   print its URL; if Pages was enabled, print the
   `https://<owner>.github.io/<slug>/` link.

## Notes

- All artifacts land on the SN850X via `~/projects/` — never inside `~/`.
- Remote creation is best-effort: projects without a GitHub remote still
  work locally. Re-run `gh repo create --public --source . --push` by
  hand later if the skill skipped it, then enable Pages with the
  `gh api … /pages` call from step 7.
- The Pages viewer (`docs/index.html`) is convention-driven and
  repo-agnostic — it ships in `~/.claude/templates/project/docs/` and
  needs no per-project edits. To update every project's viewer at once,
  edit the template copy; existing projects pick it up by re-copying.
- If any step fails, leave the half-scaffolded directory in place and
  report which step failed — don't auto-rollback.
