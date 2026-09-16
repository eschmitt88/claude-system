#!/usr/bin/env bash
# SessionStart hook — surface the tail of the active project's NOTES.md
# so the agent opens each session with fresh context.
#
# Input: JSON on stdin with at least { "cwd": "..." } (Claude Code hook payload).
# Output: text on stdout is shown as additional context to the agent.
#
# Also prints a compact "box schedule" notice (running/upcoming scheduled
# jobs, GPU-quiet window, failing jobs) in EVERY session, so an agent about to
# spend compute knows what it will collide with without asking. Pure sqlite
# reads via the job ledger; skipped silently if the coordinator is absent.
#
# NOTES.md tail is a no-op if cwd is not a research project (no CLAUDE.md +
# _meta/ ancestor).
set -euo pipefail

payload="$(cat || true)"
cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)"
cwd="${cwd:-$PWD}"

JOBS_CLI="$HOME/claude-system/coordinator/.venv/bin/claude-coordinator-jobs"
if [ -x "$JOBS_CLI" ]; then
  brief="$(timeout 3 "$JOBS_CLI" brief --hours 12 2>/dev/null || true)"
  if [ -n "$brief" ]; then
    echo "# Box schedule (shared machine — plan compute around it; \`claude-coordinator-jobs\` for detail)"
    echo "$brief"
    echo
  fi
fi

# Walk up to find the project root (nearest dir with both CLAUDE.md and _meta/).
dir="$cwd"
root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/CLAUDE.md" ] && [ -d "$dir/_meta" ]; then
    root="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done

[ -z "$root" ] && exit 0
[ -f "$root/NOTES.md" ] || exit 0

echo "# Tail of NOTES.md for $(basename "$root")"
echo
tail -n 50 "$root/NOTES.md"
