---
name: new-project
description: Scaffold a new research project at ~/projects/research/<slug> from the user template via scripts/new_project.sh — git init, dvc init, uv init, initial commit, GitHub remote (public by default), zero-build Pages site from docs/. Use when the user runs /new-project <slug>.
---

# new-project

Scaffold a new research project.

## Arguments

- `<slug>` — the project folder name. Required. Kebab-case; `_scratch`
  is allowed as a sandbox slug.
- `--private` — create the GitHub remote private instead of public.
  Default is **public** so the repo gets a standalone GitHub Pages site
  (Pages on a private repo needs a paid plan). The Pages step is then
  skipped with a note.
- `--experiments` — link the experiment-loop skill group (`/propose`,
  `/implement`, `/iterate`, `/new-experiment`, `/derive-experiment`).
  If the user's request makes the project's shape obvious (e.g. "a
  project to train X" vs "a lit review of Y"), infer this flag rather
  than asking. Lit-only projects omit it and stay lean; they can
  graduate later (claude-system README, "Growing a lit repo").

- `--agency-max` — set `agency: max` in the new `budget.yaml` (autonomous
  fetch / ingest / curate; see `~/claude-system/claude/rules/agency.md`).
  Pass it only when the user asks for max agency; the default is
  `standard`.

## How

Your decisions: the slug, and which of `--private`, `--experiments` and
`--agency-max` apply. Then run the scaffold:

```bash
bash ~/claude-system/scripts/new_project.sh <slug> [--private] [--experiments] [--agency-max]
```

The script does the mechanical work — template copy, token
substitution, hardware hints in `budget.yaml` read from this machine,
`git`/`dvc`/`uv` init, initial commit, best-effort
`gh repo create` + Pages enablement (a missing/unauthenticated `gh`
never fails the scaffold). The Pages viewer (`docs/index.html`) ships
in the template and needs no build step.

Afterwards:

1. **Fill in the orientation**: the scaffold leaves "What this project is
   about" in `CLAUDE.md` and the tagline in `README.md` as placeholders.
   Write both now from what the user asked for; `/ingest` scores
   relevance against that section and `/digest` builds its queries from
   the project's direction, so an empty one degrades both.
2. **Sync imports**: if the scaffolded `CLAUDE.md` declares
   `agentic-research/concepts/` paths, run `/sync-imports`
   so the hub's concepts gain `used_by:` back-references immediately.
3. **Report**: print the tree (depth 2), the absolute path, and the
   remote / Pages URLs if created.

## Notes

- If the script fails partway, leave the half-scaffolded directory in
  place and report which step failed — don't auto-rollback.
- Re-run remote/Pages by hand later if skipped:
  `gh repo create --public --source . --push`, then
  `gh api -X POST repos/<owner>/<slug>/pages -f "source[branch]=main" -f "source[path]=/docs"`.
