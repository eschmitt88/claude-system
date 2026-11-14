# Project: {{PROJECT_SLUG}}

Short orientation only. User-level `~/.claude/CLAUDE.md` holds the durable
principles; this file refines them for this project.

## What this project is about

One or two sentences. Fill in when the project stops being exploratory.

## Layout (see user CLAUDE.md for the full rationale)

- `raw/` — immutable source material. Read only.
- `literature/` — processed notes on papers, repos, posts.
- `concepts/` — atomic ideas. Promote to `mocs/` when ≥5 cluster.
- `experiments/YYYY-MM-DD-<slug>/` — self-contained runs.
- `docs/decisions/` — lightweight ADRs.
- `journal/` — daily session files (hook-written).
- `_meta/` — index, log, templates.

## Scoped rules

Detailed conventions live in `.claude/rules/`. Each loads on its own when
you read or edit a matching path (its `paths:` frontmatter): `experiments.md`
for `experiments/**`, `notebooks.md` for notebooks, `data.md` for `raw/**`
and data files.

Framework rules live at `~/claude-system/claude/rules/` and load only on
demand: read `evaluation.md` before designing or judging an evaluation,
`agency.md` before an autonomous run. Skills that list them under
`respects:` do this themselves.

## Budget & compute

Autonomous runs read `budget.yaml` at this project's root for hard
ceilings (wall time, tokens, disk) and model roles (ideator vs
implementer). Before proposing anything with non-trivial resource
demands — multi-hour training, large downloads, many seeds — read
`budget.yaml` and make sure the ask fits under the remaining headroom.
If it doesn't fit, say so in the proposal's `risks:` and either scope
down or explicitly flag the need to raise a ceiling.

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
