# {{PROJECT_SLUG}}

**One-line description of what this project investigates.** _(Fill in when the
project stops being exploratory — this line is the repo's tagline on GitHub.)_

📂 **[Browse this repo →](https://<owner>.github.io/{{PROJECT_SLUG}}/)** —
interactive, always-live view of experiments, concepts, literature, and maps of
content. Served via GitHub Pages from `docs/index.html`; reads the live file
tree, no build step. _(Link is live once the repo is public and Pages is enabled
— `/new-project` does both by default.)_

## What this is

A paragraph on the question, the data, and what success looks like. Keep it
oriented at a visitor who has never seen the repo.

## How it's organized

Plain Markdown + flat YAML frontmatter, cross-linked with `[[wikilinks]]`:

- `concepts/` / `mocs/` — atomic ideas; promoted to a map of content when ≥5 cluster.
- `literature/` — processed notes on papers, repos, posts (0–5 relevance scored).
- `experiments/YYYY-MM-DD-<slug>/` — self-contained runs (hypothesis → result, config, metrics, log).
- `raw/` — immutable source captures · `docs/decisions/` — ADRs · `_meta/` — index, log, templates.

## Local use

```sh
make env    # uv sync
make lint   # knowledge-graph / experiment health check
```

Part of a personal research framework
([claude-system](https://github.com/eschmitt88/claude-system)). See `CLAUDE.md`
for the agent-facing orientation and `~/.claude/CLAUDE.md` for the framework's
durable principles.
