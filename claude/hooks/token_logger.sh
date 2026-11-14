#!/usr/bin/env bash
# token_logger.sh — Stop hook. Records the session's token spend after every
# turn, as per-turn deltas, into two sinks:
#   1. <project>/_meta/token_log.ndjson  (only inside a project; read by
#      scripts/chain_budget.py for /iterate's budget ceilings)
#   2. ~/.claude/state.db token_events   (always; /headroom --json, dashboard)
#
# The counting lives in coordinator/token_log.py, on top of the same deduped
# transcript reader the quota anchor uses (coordinator/transcripts.py). This
# hook only resolves the payload and the project root. It never fails a turn.
#
# Stop hook payload (JSON on stdin): session_id, transcript_path, cwd.
set -uo pipefail

payload="$(timeout 2 cat || true)"
cwd="$(printf '%s' "$payload"        | jq -r '.cwd // empty' 2>/dev/null)"
session_id="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)"
transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null)"
cwd="${cwd:-$PWD}"

[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

# Project root: nearest ancestor with CLAUDE.md and _meta/ (may be empty).
dir="$cwd"; project_root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/CLAUDE.md" ] && [ -d "$dir/_meta" ]; then project_root="$dir"; break; fi
  dir="$(dirname "$dir")"
done

COORD="$HOME/claude-system/coordinator"
[ -x "$COORD/.venv/bin/python" ] || exit 0
# cd away from the project: `python -m` puts cwd on sys.path, and a project
# with its own coordinator/ directory would shadow the installed package.
cd / && "$COORD/.venv/bin/python" -m coordinator.token_log \
  "${session_id:-unknown}" "$transcript" "$project_root" || true
exit 0
