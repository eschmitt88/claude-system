#!/usr/bin/env bash
# token_logger.sh — Stop hook. Appends one NDJSON line per session to
# the active project's _meta/token_log.ndjson.
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

dir="$cwd"; root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/CLAUDE.md" ] && [ -d "$dir/_meta" ]; then root="$dir"; break; fi
  dir="$(dirname "$dir")"
done
[ -z "$root" ] && exit 0

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

printf '%s\n' "$(jq -n --arg t "$ts" --arg s "${session_id:-unknown}" --argjson u "$usage" \
  '{timestamp:$t,session_id:$s} + $u')" >> "$root/_meta/token_log.ndjson"

exit 0
