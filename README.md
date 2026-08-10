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
| `claude/skills/` | Global slash-command skills — the knowledge-base group (`/discover`, `/ingest`, `/curate`, `/lint`, `/headroom`, …), loaded in every project. |
| `claude/skills-experiment/` | The experiment-loop group (`/propose`, `/implement`, `/iterate`, `/new-experiment`, `/derive-experiment`) — **not** global; linked per-project via `<project>/.claude/skills` (see "Growing a lit repo" below). |
| `claude/hooks/` | Lifecycle hooks (`SessionStart`, `Stop` = token logger, `PreToolUse` = safety net). |
| `claude/templates/` | Project and note templates copied by `/new-project` / `/ingest`. |
| `coordinator/` | Python package. `state.db` schema + writers, hardware poller, agency verdict. |
| `registry/` | Service & port registry template (`services.example.yaml` → copy to untracked `services.yaml`). |
| `dashboard/` | FastAPI + HTMX + SSE dashboard. Reads `state.db` + project files. LAN-only. |
| `scripts/` | Maintenance + bootstrap helpers. |
| `install.sh` | Idempotent bootstrap for a fresh machine. |

Runtime state — `~/.claude/sessions/`, `~/.claude/cache/`,
`~/.claude/.env`, `~/.claude/state.db`, `~/projects/*` — is **not**
tracked by this repo.

## Setup

### Prerequisites

- **Linux** with `systemd --user` (runs the dashboard + hardware poller).
- **`git`**, **`uv`** (Python env manager), **Python 3.12**.
- **`jq`** (every lifecycle hook parses its payload with it) and a system
  **`python3` with PyYAML** (the session-end hook reads `budget.yaml`).
- Optional: **`gh`** (GitHub CLI — lets `/new-project` create repos and
  enable Pages); **`ccusage`** (`npm i -g ccusage` — accurate quota in
  `/headroom`); an **NVIDIA GPU** with drivers (GPU stats; absence is
  tolerated).

### Install

```sh
git clone git@github.com:eschmitt88/claude-system.git ~/claude-system
cd ~/claude-system
./install.sh
```

Clone to `~/claude-system` — that's the canonical path skills and hooks
reference. If you clone elsewhere, `install.sh` creates a `~/claude-system`
symlink to your clone so those references still resolve.

`install.sh` is **idempotent**: it symlinks the framework into `~/.claude/`
(backing up anything it replaces), provisions the coordinator + dashboard
venvs, initializes `~/.claude/state.db`, bakes your config into the systemd
units, and starts them. Re-run it any time to upgrade or to apply config
changes.

> **⚠️ Review before installing — you adopt this repo's agent behavior.**
> `install.sh` symlinks `claude/CLAUDE.md` and `claude/settings.json` into
> `~/.claude/` as *your* global instructions and settings (existing files
> are backed up first). These carry opinionated defaults: the instructions
> tell agents to **commit and push automatically** at checkpoints in every
> git repo, and the settings **suppress permission prompts**
> (`skipDangerousModePermissionPrompt`, `skipAutoPermissionPrompt`) and pin
> a default model. If you don't want that posture, edit those two files
> (or your `~/.claude/` copies) before letting agents loose.

### Configure

All machine-specific settings live in **one file: `~/.claude/.env`**
(seeded from [`.env.example`](.env.example); never committed). Every key is
optional and falls back to the default below. Edit, then re-run
`./install.sh` to apply.

| Key | Default | Purpose |
|---|---|---|
| `PROJECTS_ROOT` | `~/projects/research` | Where research projects live. |
| `DISK_MONITOR_PATH` | `~/projects` (else `~`) | Volume sampled for free disk in `/headroom` + dashboard — point at your data drive. |
| `CLAUDE_DASHBOARD_BIND` | `0.0.0.0:8080` | Dashboard `host:port`. Use `127.0.0.1:8080` for localhost-only. |
| `NTFY_TOPIC` | — | [ntfy.sh](https://ntfy.sh/) topic for notifications. |
| `QUOTA_WEEKLY_COST_LIMIT_USD` | see `ccusage.py` | Calibrated weekly plan ceiling (USD) for `/headroom` + dashboard %. |
| `QUOTA_WEEKLY_TOKEN_LIMIT` / `QUOTA_5H_TOKEN_LIMIT` | see `ccusage.py` | Token fallbacks for the weekly / 5h windows. |
| `QUOTA_WEEKLY_RESET_HOUR` / `QUOTA_WEEKLY_RESET_WEEKDAY` | `17` / `0` (Mon) | Weekly quota reset boundary as shown on claude.ai. |

The quota defaults are one Max-20x subscription's calibration — see the
calibration note at the top of the constants block in
[`coordinator/coordinator/ccusage.py`](coordinator/coordinator/ccusage.py)
for how to derive yours from a live claude.ai reading.

The service/port registry rendered by the dashboard's `/ports` page is
machine-specific and **untracked**: copy
[`registry/services.example.yaml`](registry/services.example.yaml) to
`registry/services.yaml` and describe your own services (the page is
empty without it).

These resolve through `coordinator/config.py`, so the code works even with
an empty `.env`; the file only overrides defaults.

**Model roles** are a *per-project* setting, not machine config: each
project's `budget.yaml` sets `models.ideator` / `models.implementer`. The
template defaults both to `opus` — a floating alias that resolves to the
latest Opus release, so it tracks new versions without edits. Pin a concrete
slug (e.g. `claude-opus-4-8`) for reproducibility, or use `haiku`/`sonnet`
for a cheaper implementer.

### Verify

```sh
~/claude-system/coordinator/.venv/bin/claude-coordinator-status   # what /headroom shows
systemctl --user status claude-dashboard.service claude-hw-poller.timer
# dashboard → http://localhost:8080  (or the bind you configured)
```

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

Skills consult the coordinator via `/headroom`. (An admission layer —
job queue, admit/defer policy, per-session PreToolUse cap — was removed
2026-08-01 after three months of telemetry showed it never fired; see
agentic-research `docs/system-proposals/2026-07-31-instruction-ablation-program.md`.
Recoverable from git history if parallel multi-project autonomy ever
needs arbitration.)

**Agency verdict.** `claude-coordinator-agency` (shown in `/headroom`)
turns the quota + hardware state into a `GO / SLOW / HOLD` recommendation,
using reset-anchored token pacing (unused weekly quota is wasted, so being
behind pace near the reset means spend now) plus live CPU/RAM/GPU headroom.
A project opts into autonomy with `agency: max` in its `budget.yaml`: in
those repos `/digest` auto-fetches and ingests the top candidates, and
`/iterate` chains cycles, while the verdict permits and the `budget.yaml`
ceilings hold. Default `agency: standard` keeps the propose-and-confirm
behavior. See `claude/rules/agency.md`.

### Dashboard (Phase 6, Part 4)

FastAPI app bound to `CLAUDE_DASHBOARD_BIND` (default `0.0.0.0:8080`,
i.e. reachable on the LAN at `http://<host>:8080`). Views: `/`
(live now — loop sessions, live gauges, quota meters), `/queue`
(coordinator queue), `/project/<name>` (per-project cycle table +
DIAGNOSTICS). Auto-refreshes via SSE. Runs as a systemd user unit.

## Growing a lit repo into an experimenting one

The experiment-loop skills are scoped, not global, so a project's shape
is a choice. Two ways it grows, decided by whether the experiments
serve this repo's reading or start a new line of work:

- **Spawn a downstream project** when the experiments have their own
  identity (own data, own budget, many runs) or the concepts serve
  more than one consumer: `/new-project --experiments`, then `@import`
  the hub's concepts (the import contract writes `used_by:`
  back-references).
- **Graduate in place** when there is a single consumer and reading
  and running are one thread:
  1. `ln -s ~/claude-system/claude/skills-experiment .claude/skills`
  2. Declare intent in `budget.yaml` (ceilings, `agency:`, model roles).
  3. **Define the holdout before the first optimization run** —
     `splits.yaml` + `test/` flips the HCE opt-in
     (`claude/rules/evaluation.md`). The only order-sensitive step: a
     holdout carved out after iterating against the data is
     contaminated from birth.
  4. `dvc init` if absent; `.worktrees/` for destructive runs.
  5. First move: `/derive-experiment` on the ripest literature note.
  6. Record the graduation in `docs/decisions/`.

`/lint` warns when a repo has dated experiment folders but no linked
experiment-loop group.

## Contributing / editing

Because the `claude/` tree is symlinked into `~/.claude/`, editing
files under either path updates the same content. Commit from
`~/claude-system/` so history stays coherent.

Runtime state must never be committed. The `.gitignore` is strict on
`*.db` and `.env`; add to it if a new runtime artifact appears.

## License

[MIT](LICENSE).
