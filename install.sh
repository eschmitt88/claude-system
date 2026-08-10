#!/usr/bin/env bash
# install.sh — idempotent bootstrap for claude-system.
#
# Creates ~/.claude/ (if missing), symlinks each framework subdirectory
# of this repo's claude/ tree into place, preserves any existing runtime
# state, and installs the dashboard + coordinator systemd user units.
#
# Safe to re-run. A backup of any file about to be replaced is saved
# to ~/.claude/backups/<timestamp>/ before the symlink is created.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BACKUP_DIR="$CLAUDE_DIR/backups/$(date +%Y%m%d-%H%M%S)"

mkdir -p "$CLAUDE_DIR"

# Canonical location. Skills and hooks reference ~/claude-system by path.
# If this repo was cloned elsewhere, point ~/claude-system at it so those
# references resolve regardless of where you cloned.
CANONICAL="$HOME/claude-system"
if [ "$REPO_ROOT" != "$CANONICAL" ]; then
  if [ -L "$CANONICAL" ] || [ ! -e "$CANONICAL" ]; then
    ln -sfn "$REPO_ROOT" "$CANONICAL"
    echo "  [link]   $CANONICAL → $REPO_ROOT (canonical path for skills/hooks)"
  else
    echo "  [warn]   $CANONICAL exists and is not this clone — skills expect the"
    echo "           repo reachable at ~/claude-system. Move/clone there, or symlink it."
  fi
fi

# Symlink helper. If the target exists and isn't already pointing at the
# repo copy, move it aside before linking.
link() {
  local src="$1"; local dst="$2"
  if [ -L "$dst" ]; then
    # Already a symlink; update it.
    rm "$dst"
  elif [ -e "$dst" ]; then
    mkdir -p "$BACKUP_DIR"
    mv "$dst" "$BACKUP_DIR/"
    echo "  [backup] moved $dst → $BACKUP_DIR/"
  fi
  ln -s "$src" "$dst"
  echo "  [link]   $dst → $src"
}

echo "=> Linking framework directories into $CLAUDE_DIR/"
# rules/ is deliberately NOT linked: evaluation.md/agency.md load via
# project-CLAUDE.md @imports so they cost context only where they apply
# (instruction-ablation-program, phase 5). Skills reference them by
# their stable ~/claude-system/claude/rules/ paths.
for sub in skills hooks templates; do
  link "$REPO_ROOT/claude/$sub" "$CLAUDE_DIR/$sub"
done
# Clean up the pre-phase-5 global rules link if present.
if [ -L "$CLAUDE_DIR/rules" ]; then rm "$CLAUDE_DIR/rules"; echo "  [unlink] $CLAUDE_DIR/rules (rules now load per-project)"; fi

echo "=> Linking framework files into $CLAUDE_DIR/"
for f in CLAUDE.md settings.json; do
  link "$REPO_ROOT/claude/$f" "$CLAUDE_DIR/$f"
done

# .env: never touch an existing one. Only emit the example if nothing
# exists at all.
if [ ! -e "$CLAUDE_DIR/.env" ]; then
  if [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$CLAUDE_DIR/.env"
    echo "=> Seeded $CLAUDE_DIR/.env from .env.example (edit to configure)."
  fi
fi

# Resolve machine config from ~/.claude/.env (shell syntax), so we can bake
# concrete values into the systemd units. Unset keys fall back to defaults
# that match coordinator/config.py.
if [ -f "$CLAUDE_DIR/.env" ]; then
  set -a; . "$CLAUDE_DIR/.env"; set +a
fi
PROJECTS_ROOT_VAL="${PROJECTS_ROOT:-$HOME/projects/research}"
if [ -n "${DISK_MONITOR_PATH:-}" ]; then DISK_MONITOR_PATH_VAL="$DISK_MONITOR_PATH"
elif [ -d "$HOME/projects" ]; then DISK_MONITOR_PATH_VAL="$HOME/projects"
else DISK_MONITOR_PATH_VAL="$HOME"; fi
DASHBOARD_BIND_VAL="${CLAUDE_DASHBOARD_BIND:-0.0.0.0:8080}"
# Quota calibration (optional; empty = ccusage.py defaults apply).
QUOTA_5H_TOKEN_LIMIT_VAL="${QUOTA_5H_TOKEN_LIMIT:-}"
QUOTA_WEEKLY_COST_LIMIT_USD_VAL="${QUOTA_WEEKLY_COST_LIMIT_USD:-}"
QUOTA_WEEKLY_TOKEN_LIMIT_VAL="${QUOTA_WEEKLY_TOKEN_LIMIT:-}"
QUOTA_WEEKLY_RESET_HOUR_VAL="${QUOTA_WEEKLY_RESET_HOUR:-}"
QUOTA_WEEKLY_RESET_WEEKDAY_VAL="${QUOTA_WEEKLY_RESET_WEEKDAY:-}"

# Coordinator venv + state.db initialization
if command -v uv >/dev/null 2>&1; then
  echo "=> Provisioning coordinator venv"
  (cd "$REPO_ROOT/coordinator" && uv venv --python 3.12 .venv 2>/dev/null || true)
  (cd "$REPO_ROOT/coordinator" && source .venv/bin/activate && uv pip install -e . 2>&1 | tail -1) || true
  # Initialize state.db schema (idempotent). Use the installed console
  # script, not `python -m` — the latter puts the repo root on sys.path,
  # where the bare ./coordinator dir shadows the installed package.
  "$REPO_ROOT/coordinator/.venv/bin/claude-coordinator-init" || true
fi

# Dashboard venv
if command -v uv >/dev/null 2>&1 && [ -d "$REPO_ROOT/dashboard" ]; then
  echo "=> Provisioning dashboard venv"
  (cd "$REPO_ROOT/dashboard" && uv venv --python 3.12 .venv 2>/dev/null || true)
  (cd "$REPO_ROOT/dashboard" && source .venv/bin/activate && uv pip install -e . 2>&1 | tail -1) || true
fi

# Systemd user units — dashboard + hardware poller
USER_UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$USER_UNIT_DIR"

for unit in claude-dashboard.service claude-hw-poller.service claude-hw-poller.timer; do
  src="$REPO_ROOT/scripts/systemd/$unit"
  if [ -f "$src" ]; then
    # Substitute REPO_ROOT + resolved config into the unit file.
    sed "s|{{REPO_ROOT}}|$REPO_ROOT|g; s|{{HOME}}|$HOME|g; \
         s|{{PROJECTS_ROOT}}|$PROJECTS_ROOT_VAL|g; \
         s|{{DISK_MONITOR_PATH}}|$DISK_MONITOR_PATH_VAL|g; \
         s|{{DASHBOARD_BIND}}|$DASHBOARD_BIND_VAL|g; \
         s|{{QUOTA_5H_TOKEN_LIMIT}}|$QUOTA_5H_TOKEN_LIMIT_VAL|g; \
         s|{{QUOTA_WEEKLY_COST_LIMIT_USD}}|$QUOTA_WEEKLY_COST_LIMIT_USD_VAL|g; \
         s|{{QUOTA_WEEKLY_TOKEN_LIMIT}}|$QUOTA_WEEKLY_TOKEN_LIMIT_VAL|g; \
         s|{{QUOTA_WEEKLY_RESET_HOUR}}|$QUOTA_WEEKLY_RESET_HOUR_VAL|g; \
         s|{{QUOTA_WEEKLY_RESET_WEEKDAY}}|$QUOTA_WEEKLY_RESET_WEEKDAY_VAL|g" "$src" > "$USER_UNIT_DIR/$unit"
    echo "  [unit]   $USER_UNIT_DIR/$unit"
  fi
done

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload || true
  for unit in claude-hw-poller.timer claude-dashboard.service; do
    if [ -f "$USER_UNIT_DIR/$unit" ]; then
      systemctl --user enable --now "$unit" 2>/dev/null || echo "  (systemctl enable $unit failed; bring it up by hand later)"
    fi
  done
fi

echo "=> install.sh done"
echo
echo "   Configuration (edit $CLAUDE_DIR/.env, then re-run ./install.sh):"
echo "     PROJECTS_ROOT        = $PROJECTS_ROOT_VAL"
echo "     DISK_MONITOR_PATH    = $DISK_MONITOR_PATH_VAL"
echo "     CLAUDE_DASHBOARD_BIND= $DASHBOARD_BIND_VAL"
echo
echo "   Verify:"
echo "     $REPO_ROOT/coordinator/.venv/bin/claude-coordinator-status"
echo "     systemctl --user status claude-dashboard.service claude-hw-poller.timer"
echo "     dashboard → http://${DASHBOARD_BIND_VAL/0.0.0.0/localhost}"
echo "   Backups (if any) are in $BACKUP_DIR"
