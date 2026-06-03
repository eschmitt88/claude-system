# claude-system

Version-controlled `~/.claude/` framework plus a resource coordinator and
internal dashboard for an agentic research setup.

📐 **[System map](https://eschmitt88.github.io/claude-system/)** — a visual,
framework-level tour of every part and how they connect (source:
[`docs/index.html`](docs/index.html)).

## What's here

| Path | Purpose |
|---|---|
| `claude/CLAUDE.md` | Durable user instructions (symlinked to `~/.claude/CLAUDE.md`). |
| `claude/settings.json` | Claude Code settings (hooks, permissions). |
| `claude/rules/` | Scoped rules auto-loaded by path (e.g. `evaluation.md` = HCE discipline). |
| `claude/skills/` | Invocable slash-command skills (`/propose`, `/implement`, `/iterate`, `/headroom`, …). |
| `claude/hooks/` | Lifecycle hooks (`SessionStart`, `Stop` = token logger, `PreToolUse` = safety net). |
| `claude/templates/` | Project and note templates copied by `/new-project` / `/ingest`. |
| `coordinator/` | Python package. `state.db` schema + writers, hardware poller, policy (`can_start`). |
| `dashboard/` | FastAPI + HTMX + SSE dashboard. Reads `state.db` + project files. LAN-only. |
| `scripts/` | Maintenance + bootstrap helpers. |
| `install.sh` | Idempotent bootstrap for a fresh machine. |

Runtime state — `~/.claude/sessions/`, `~/.claude/cache/`,
`~/.claude/.env`, `~/.claude/state.db`, `~/projects/*` — is **not**
tracked by this repo.

## Bootstrap on a fresh machine

```
git clone git@github.com:<you>/claude-system.git ~/claude-system
cd ~/claude-system
./install.sh
```

`install.sh` is idempotent. Running it on an existing install upgrades
symlinks and reinstalls the systemd unit for the dashboard.

Required environment variables live in `~/.claude/.env` (copy from
`.env.example`). The install script does not overwrite an existing
`.env`.

## Architecture

### Framework (Phases 1–5)

Skills follow a `propose → implement → iterate → ensemble` loop driven
by a user in Claude Code. `/propose` does ideation; `/implement` is the
only skill that spawns a subagent; `/iterate` drives chain cycles.
Experiments live at `~/projects/research/<project>/experiments/YYYY-MM-DD-<slug>/`
with a standard layout (README, config.yaml, metrics.json, results/,
splits.yaml where applicable). See individual `SKILL.md` files for
contracts.

The `agentic-research` project is the meta-hub: `concepts/` files are
`@import`ed by downstream projects, and `/sync-imports` appends
`used_by:` back-references.

### Standalone GitHub presence (per-project Pages)

Every project scaffolded from the template ships
`docs/index.html` — a **zero-build, convention-driven viewer** of its
knowledge graph (literature / concepts / MoCs / experiments / candidates
/ decisions). It is byte-for-byte identical across repos: it auto-detects
`owner/repo` from the Pages URL, reads the live file tree in one GitHub
API call, and pulls file bodies from the `raw` CDN. No build step, no
regeneration, no pre-commit hook — it reflects the repo as it stands on
each page load.

The automated process for any repo following the layout:

1. The template already contains `docs/index.html` (edit the template
   copy to update every project's viewer at once).
2. The repo must be **public** (GitHub Pages on a private repo needs a
   paid plan). `/new-project` creates public repos by default
   (`--private` to opt out).
3. Enable Pages from the `/docs` folder — `/new-project` does this
   automatically; by hand it is one call:
   ```sh
   gh api -X POST repos/<owner>/<repo>/pages \
     -f "source[branch]=main" -f "source[path]=/docs"
   ```
4. The site is live at `https://<owner>.github.io/<repo>/` within ~1–2 min.

The framework's own map (this repo) lives the same way at
[`docs/index.html`](docs/index.html) →
<https://eschmitt88.github.io/claude-system/>.

Private projects skip Pages and are browsed via the internal dashboard
instead, which renders the same directory convention.

### Coordinator (Phase 6, Part 3)

A single sqlite database at `~/.claude/state.db` tracks:

- **Claude quota** — tokens consumed in the current 5h and weekly windows.
- **Hardware** — GPU/CPU/RAM/disk samples (30s cadence).
- **Job queue** — declared jobs + estimated resource cost + status.
- **Decisions** — admit/defer log for policy review.

Skills consult the coordinator via `/headroom` and `/plan`. Long-running
skills (`/implement`, `/iterate`, `/ingest`, `/digest`) declare their
job to the queue and honor policy verdicts. A PreToolUse hook is the
safety net, not the primary control.

### Dashboard (Phase 6, Part 4)

FastAPI app on `http://aiserver.local:8080`. LAN-only. Views: `/`
(live now — loop sessions, live gauges, quota meters), `/queue`
(coordinator queue), `/project/<name>` (per-project cycle table +
DIAGNOSTICS). Auto-refreshes via SSE. Runs as a systemd user unit.

## Contributing / editing

Because the `claude/` tree is symlinked into `~/.claude/`, editing
files under either path updates the same content. Commit from
`~/claude-system/` so history stays coherent.

Runtime state must never be committed. The `.gitignore` is strict on
`*.db` and `.env`; add to it if a new runtime artifact appears.

## License

Private. All rights reserved unless explicitly licensed.
