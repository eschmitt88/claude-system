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
for sub in rules skills hooks templates; do
  link "$REPO_ROOT/claude/$sub" "$CLAUDE_DIR/$sub"
done

echo "=> Linking framework files into $CLAUDE_DIR/"
for f in CLAUDE.md settings.json; do
  link "$REPO_ROOT/claude/$f" "$CLAUDE_DIR/$f"
done

# .env: never touch an existing one. Only emit the example if nothing
# exists at all.
if [ ! -e "$CLAUDE_DIR/.env" ]; then
  if [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$CLAUDE_DIR/.env"
    echo "=> Seeded $CLAUDE_DIR/.env from .env.example (fill in NTFY_TOPIC)."
  fi
fi

# Coordinator venv + state.db initialization
if command -v uv >/dev/null 2>&1; then
  echo "=> Provisioning coordinator venv"
  (cd "$REPO_ROOT/coordinator" && uv venv --python 3.12 .venv 2>/dev/null || true)
  (cd "$REPO_ROOT/coordinator" && source .venv/bin/activate && uv pip install -e . 2>&1 | tail -1) || true
  # Initialize state.db schema (idempotent).
  "$REPO_ROOT/coordinator/.venv/bin/python" -m coordinator.init_db || true
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
    # Substitute REPO_ROOT in the unit file.
    sed "s|{{REPO_ROOT}}|$REPO_ROOT|g; s|{{HOME}}|$HOME|g" "$src" > "$USER_UNIT_DIR/$unit"
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
echo "   Backups (if any) are in $BACKUP_DIR"
echo "   Fill in $CLAUDE_DIR/.env before first use."
