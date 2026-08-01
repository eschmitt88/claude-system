#!/usr/bin/env bash
# new_project.sh — mechanical scaffold for /new-project.
# Deterministic port of the command sequence that used to live as prose
# in new-project/SKILL.md (instruction-ablation-program, phase 3).
# The skill keeps the decisions (slug choice, --private, --experiments
# inference, sync-imports); this script does the filesystem/git/gh work.
#
# Usage: new_project.sh <slug> [--private] [--experiments] [--no-remote]
# Env:   PROJECTS_ROOT (default ~/projects/research)
#        TEMPLATE_DIR  (default ~/.claude/templates/project)
set -euo pipefail

SLUG="" PRIVATE=0 EXPERIMENTS=0 NO_REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --private)     PRIVATE=1 ;;
    --experiments) EXPERIMENTS=1 ;;
    --no-remote)   NO_REMOTE=1 ;;
    -*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *)  SLUG="$arg" ;;
  esac
done
[ -n "$SLUG" ] || { echo "usage: new_project.sh <slug> [--private] [--experiments] [--no-remote]" >&2; exit 2; }
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
