#!/usr/bin/env bash
# new_project.sh — mechanical scaffold for /new-project.
# Deterministic port of the command sequence that used to live as prose
# in new-project/SKILL.md (instruction-ablation-program, phase 3).
# The skill keeps the decisions (slug choice, --private, --experiments
# inference, sync-imports); this script does the filesystem/git/gh work.
#
# Usage: new_project.sh <slug> [--private] [--experiments] [--agency-max] [--no-remote]
# Env:   PROJECTS_ROOT (default ~/projects/research)
#        TEMPLATE_DIR  (default ~/.claude/templates/project)
set -euo pipefail

SLUG="" PRIVATE=0 EXPERIMENTS=0 NO_REMOTE=0 AGENCY_MAX=0
for arg in "$@"; do
  case "$arg" in
    --private)     PRIVATE=1 ;;
    --experiments) EXPERIMENTS=1 ;;
    --no-remote)   NO_REMOTE=1 ;;
    --agency-max)  AGENCY_MAX=1 ;;
    -*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *)  SLUG="$arg" ;;
  esac
done
[ -n "$SLUG" ] || { echo "usage: new_project.sh <slug> [--private] [--experiments] [--agency-max] [--no-remote]" >&2; exit 2; }
case "$SLUG" in
  */*|*" "*|*..*) echo "invalid slug: $SLUG" >&2; exit 2 ;;
esac

ROOT="${PROJECTS_ROOT:-$HOME/projects/research}"
TEMPLATE="${TEMPLATE_DIR:-$HOME/.claude/templates/project}"
DEST="$ROOT/$SLUG"
[ -e "$DEST" ] && { echo "already exists: $DEST" >&2; exit 2; }
[ -d "$TEMPLATE" ] || { echo "template missing: $TEMPLATE" >&2; exit 2; }

mkdir -p "$ROOT"
cp -a "$TEMPLATE/" "$DEST/"
cd "$DEST"

# Substitute template tokens.
for f in README.md CLAUDE.md; do
  [ -f "$f" ] && sed -i "s/{{PROJECT_SLUG}}/$SLUG/g" "$f"
done

# budget.yaml: autonomy level, and hardware hints read from this machine.
# The hints are what /implement hands its subagent, so a placeholder there
# ("gpu_count: 0") is worse than nothing. Best effort: a value that can't be
# read keeps the template's placeholder.
if [ -f budget.yaml ]; then
  [ "$AGENCY_MAX" = 1 ] && sed -i 's/^agency:.*/agency: max/' budget.yaml
  gpu="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
  if [ -n "$gpu" ]; then
    gpu_name="$(printf '%s\n' "$gpu" | head -n1 | cut -d, -f1 | sed 's/^ *//; s/ *$//')"
    gpu_mib="$(printf '%s\n' "$gpu" | head -n1 | cut -d, -f2 | tr -dc 0-9)"
    sed -i "s|^  gpu_model:.*|  gpu_model: \"$gpu_name\"|; \
            s|^  gpu_memory_gb:.*|  gpu_memory_gb: $(( (${gpu_mib:-0} + 512) / 1024 ))|; \
            s|^  gpu_count:.*|  gpu_count: $(printf '%s\n' "$gpu" | wc -l)|" budget.yaml
  else
    sed -i 's|^  gpu_model:.*|  gpu_model: "none"|' budget.yaml
  fi
  ram_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || true)"
  [ -n "$ram_kb" ] && sed -i "s|^  system_ram_gb:.*|  system_ram_gb: $(( ram_kb / 1024 / 1024 ))|" budget.yaml
  free_gb="$(df -BG --output=avail "$ROOT" 2>/dev/null | tail -n1 | tr -dc 0-9 || true)"
  [ -n "$free_gb" ] && sed -i "s|^  storage_path:.*|  storage_path: \"$ROOT\"|; \
                               s|^  storage_free_gb:.*|  storage_free_gb: $free_gb|" budget.yaml
fi

git init -q -b main
command -v dvc >/dev/null 2>&1 && dvc init -q
# uv init rejects slugs that don't parse as a Python package name.
PKG="$(printf '%s' "$SLUG" | sed 's/^[^a-zA-Z0-9]*//' | tr '[:upper:]' '[:lower:]')"
[ -z "$PKG" ] && PKG=project
command -v uv >/dev/null 2>&1 && uv init --bare --no-workspace --no-pin-python --name "$PKG" >/dev/null

if [ "$EXPERIMENTS" = 1 ]; then
  mkdir -p .claude
  ln -sfn ~/claude-system/claude/skills-experiment .claude/skills
fi

git add -A
git commit -q -m "scaffold: initial skeleton for $SLUG"

if [ "$NO_REMOTE" = 1 ]; then
  echo "scaffolded $DEST (no remote requested)"
  exit 0
fi

# Remote + Pages, best-effort — never fail the scaffold over them.
VIS=public; [ "$PRIVATE" = 1 ] && VIS=private
OWNER=""
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  if gh repo create --"$VIS" --source . --push "$SLUG" 2>/tmp/gh-err-$$; then
    OWNER="$(gh api user --jq .login)"
    echo "Created github:$OWNER/$SLUG ($VIS)"
  else
    echo "gh repo create failed (continuing without remote):"
    cat /tmp/gh-err-$$ || true
  fi
  rm -f /tmp/gh-err-$$
else
  echo "gh not available or not authenticated — skipping remote creation."
fi

if [ "$VIS" = public ] && [ -n "$OWNER" ]; then
  if gh api -X POST "repos/$OWNER/$SLUG/pages" \
       -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1; then
    echo "Pages enabled → https://$OWNER.github.io/$SLUG/ (first build ~1-2 min)"
  else
    echo "Pages enable skipped (already enabled, or insufficient scope)."
  fi
else
  [ "$VIS" = private ] && echo "Pages skipped — repo is private."
fi

echo "scaffolded $DEST"
