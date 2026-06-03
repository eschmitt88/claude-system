# {{PROJECT_SLUG}}

Personal research project. See `CLAUDE.md` for the agent-facing orientation
and `~/.claude/CLAUDE.md` for the framework's durable principles.

**Browse:** if this repo is public, a zero-build viewer of the knowledge
graph (literature, concepts, MoCs, experiments) is served at
`https://<owner>.github.io/{{PROJECT_SLUG}}/` via GitHub Pages from
`docs/index.html` — it reads the live file tree, no build step.

## Quick start

```sh
make env       # uv sync
make lint      # orphan/dead-link check
```

## Layout

- `raw/` — immutable sources (papers, repos, web captures).
- `literature/` — processed notes.
- `concepts/` / `mocs/` — knowledge graph.
- `experiments/` — runs, each dated and slugged.
- `docs/decisions/` — ADRs.
- `journal/` — per-session log.
- `_meta/` — index, log, templates.
