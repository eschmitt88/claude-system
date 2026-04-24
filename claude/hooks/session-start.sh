#!/usr/bin/env bash
# SessionStart hook — surface the tail of the active project's NOTES.md
# so the agent opens each session with fresh context.
#
# Input: JSON on stdin with at least { "cwd": "..." } (Claude Code hook payload).
# Output: text on stdout is shown as additional context to the agent.
#
# No-op if cwd is not a research project (no CLAUDE.md + _meta/ ancestor).
set -euo pipefail

payload="$(cat || true)"
cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)"
cwd="${cwd:-$PWD}"

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
