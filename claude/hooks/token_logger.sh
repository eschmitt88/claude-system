#!/usr/bin/env bash
# token_logger.sh — Stop hook. Writes two things:
#   1. One NDJSON line to the active project's _meta/token_log.ndjson (legacy).
#   2. One row into ~/.claude/state.db token_events (Phase 6 coordinator).
#
# Stop hook payload (JSON on stdin; Claude Code hooks docs):
#   session_id        — "string"
#   transcript_path   — path to the session JSONL transcript
#   cwd               — working directory
#   hook_event_name   — "Stop"
#
# Per-session token usage is NOT in the payload. We parse the transcript
# JSONL for per-message `message.usage.{input_tokens, output_tokens,
# cache_read_input_tokens, cache_creation_input_tokens}` and aggregate.
set -euo pipefail

payload="$(cat || true)"
cwd="$(printf '%s' "$payload"        | jq -r '.cwd // empty')"
session_id="$(printf '%s' "$payload" | jq -r '.session_id // empty')"
transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty')"
cwd="${cwd:-$PWD}"

# Walk up to find the project root (may be empty if not inside a project).
dir="$cwd"; project_root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/CLAUDE.md" ] && [ -d "$dir/_meta" ]; then project_root="$dir"; break; fi
  dir="$(dirname "$dir")"
done

ts="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
# Aggregate usage + tool_name histogram from the transcript.
usage='{"input_tokens":0,"output_tokens":0,"cache_read_tokens":0,"cache_creation_tokens":0,"tools_used_summary":{}}'
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
  usage="$(jq -s '
    {
      input_tokens:           (map(.message.usage.input_tokens // 0) | add // 0),
      output_tokens:          (map(.message.usage.output_tokens // 0) | add // 0),
      cache_read_tokens:      (map(.message.usage.cache_read_input_tokens // 0) | add // 0),
      cache_creation_tokens:  (map(.message.usage.cache_creation_input_tokens // 0) | add // 0),
      tools_used_summary:
        ( map(.message.content? // [] | .[]? | select(.type=="tool_use") | .name)
          | reduce .[] as $n ({}; .[$n] = ((.[$n] // 0) + 1)) )
    }' "$transcript" 2>/dev/null || printf '%s' "$usage")"
fi

# 1. Legacy per-project NDJSON log — only when inside a project.
if [ -n "$project_root" ]; then
  printf '%s\n' "$(jq -n --arg t "$ts" --arg s "${session_id:-unknown}" --argjson u "$usage" \
    '{timestamp:$t,session_id:$s} + $u')" >> "$project_root/_meta/token_log.ndjson"
fi

# 2. Coordinator state.db — always. Project tag derived from root basename.
project_slug=""
if [ -n "$project_root" ]; then project_slug="$(basename "$project_root")"; fi

COORD_PY="$HOME/claude-system/coordinator/.venv/bin/python"
if [ -x "$COORD_PY" ]; then
  printf '%s' "$usage" | "$COORD_PY" - "${session_id:-unknown}" "$project_slug" "$ts" <<'PYEOF' || true
import json, sys
from coordinator.writers import insert_token_event
payload = json.loads(sys.stdin.read() or "{}")
insert_token_event(
    session_id=sys.argv[1] or "unknown",
    project=sys.argv[2] or None,
    input_tokens=payload.get("input_tokens", 0),
    output_tokens=payload.get("output_tokens", 0),
    cache_read_tokens=payload.get("cache_read_tokens", 0),
    cache_creation_tokens=payload.get("cache_creation_tokens", 0),
    tools_used=payload.get("tools_used_summary", {}),
    timestamp=sys.argv[3],
)
PYEOF
fi

exit 0
