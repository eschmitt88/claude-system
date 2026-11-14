---
name: new-project
description: /new-project <slug> scaffolds a research project at ~/projects/research/<slug> via scripts/new_project.sh (git, dvc, uv, first commit, GitHub remote, Pages site). Flags for private, experiment-loop skills, and max agency.
---

# new-project

```bash
bash ~/claude-system/scripts/new_project.sh <slug> [--private] [--experiments] [--agency-max]
```

The script does the mechanical work, including the remote and Pages
(best-effort: a missing `gh` never fails the scaffold). Your decisions are
the slug and the flags:

- `<slug>`: kebab-case folder and repo name.
- `--private`: default is **public**, because the project's Pages site
  needs it. Pass it for anything that must not be public.
- `--experiments`: links the experiment-loop skills (`/propose`,
  `/implement`, `/iterate`, `/new-experiment`, `/derive-experiment`).
  Infer it from the request ("a project to train X" vs "a literature
  review of Y"). A literature-only project can graduate later
  (claude-system README, "Growing a lit repo").
- `--agency-max`: sets `agency: max`. Only when the user asks for it.

Afterwards:

1. **Fill the orientation.** The scaffold leaves "What this project is
   about" in `CLAUDE.md` and the tagline in `README.md` as placeholders.
   Write both now: `/ingest` scores relevance against that section and
   `/digest` builds its queries from the project's direction.
2. **Run `/sync-imports`** if `CLAUDE.md` declares hub concepts.
3. **Report** the path, the tree to depth 2, and the remote and Pages URLs.

If the script fails partway, leave the directory as it is and report the
failed step. The remote and Pages can be redone by hand:
`gh repo create --public --source . --push`, then
`gh api -X POST repos/<owner>/<slug>/pages -f "source[branch]=main" -f "source[path]=/docs"`.
