# Project: {{PROJECT_SLUG}}

Orientation only. `~/.claude/CLAUDE.md` holds the durable principles; this
file refines them for this project.

## What this project is about

One or two sentences. `/ingest` scores relevance against this section.

## Layout

- `raw/` — immutable source material. Read only.
- `literature/` — processed notes on papers, repos, posts.
- `concepts/` — atomic ideas. Promote to `mocs/` when ≥5 cluster.
- `experiments/YYYY-MM-DD-<slug>/` — self-contained runs.
- `docs/decisions/` — lightweight ADRs.
- `journal/` — daily session files (hook-written).
- `_meta/` — index, log, templates.

## Rules

`.claude/rules/` holds scoped conventions. Each loads when you read or edit
a matching path (its `paths:` frontmatter): `experiments.md` for
`experiments/**`, `notebooks.md` for notebooks, `data.md` for `raw/**` and
data files.

Framework rules live at `~/claude-system/claude/rules/` and load only on
demand: read `evaluation.md` before designing or judging an evaluation,
`agency.md` before an autonomous run. Skills that list them under
`respects:` do this themselves.

## Budget & compute

`budget.yaml` sets the hard ceilings (wall time, tokens, disk), the
autonomy level and the model roles. Anything with real resource demands
has to fit under it. If it doesn't, say so and scope down, or flag the
ceiling.

@budget.yaml

## Project-specific facts

- Primary language: (fill in)
- Environment: managed by `uv`; run `make env` to sync.
- Data: tracked by DVC. Large artifacts on SN850X via `~/projects/`.

## Housekeeping

- End sessions with `/wrap`. The SessionEnd hook backstops this.
- Experiments are scaffolded by `/new-experiment <slug>` (part of the
  experiment skill group; claude-system README, "Growing a lit repo").
- Run `/lint` weekly.
