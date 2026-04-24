#!/usr/bin/env bash
# status_emit.sh — PostToolUse hook, scoped to Write on
# experiments/**/metrics.json. Emits one NDJSON line per write to
# _meta/status.ndjson so `tail -f` watchers can stream progress during
# long autonomous runs.
#
# PostToolUse hook payload (JSON on stdin):
#   session_id, transcript_path, cwd, hook_event_name="PostToolUse"
#   tool_name, tool_input{file_path, ...}, tool_response, tool_use_id
#
# The matcher in settings.json restricts us to Write; we further filter
# on file_path matching experiments/*/metrics.json.
set -euo pipefail

payload="$(cat || true)"
tool="$(printf '%s' "$payload"       | jq -r '.tool_name // empty')"
fp="$(printf '%s' "$payload"         | jq -r '.tool_input.file_path // empty')"
cwd="$(printf '%s' "$payload"        | jq -r '.cwd // empty')"
sid="$(printf '%s' "$payload"        | jq -r '.session_id // empty')"
transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty')"
cwd="${cwd:-$PWD}"

[ "$tool" = "Write" ] || exit 0
case "$fp" in *experiments/*/metrics.json) : ;; *) exit 0 ;; esac
[ -f "$fp" ] || exit 0

dir="$cwd"; root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/CLAUDE.md" ] && [ -d "$dir/_meta" ]; then root="$dir"; break; fi
  dir="$(dirname "$dir")"
done
[ -z "$root" ] && exit 0

ts="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
# Derive the experiment slug (folder name between experiments/ and /metrics.json).
slug="$(printf '%s' "$fp" | sed -nE 's#.*experiments/([^/]+)/metrics\.json#\1#p')"

# Metric name+value: take the first numeric key in the JSON.
read -r mname mval < <(jq -r 'to_entries[] | select(.value|type=="number") | "\(.key) \(.value)"' "$fp" 2>/dev/null | head -n1 || echo "")
mname="${mname:-}"; mval="${mval:-}"

# Delta vs previous write for same slug+metric (read last matching record).
# NDJSON is strictly one-JSON-per-line, so we let jq filter/stream rather
# than grep (which is fragile against any escaped quote in the content).
status_log="$root/_meta/status.ndjson"
delta=""
if [ -n "$mname" ] && [ -f "$status_log" ]; then
  prev="$(jq -s --arg slug "$slug" --arg m "$mname" \
    'map(select(.slug==$slug and .metric_name==$m)) | last | .metric_value // empty' \
    "$status_log" 2>/dev/null)"
  if [ -n "$prev" ] && [ "$prev" != "null" ] && [ "$prev" != "" ]; then
    delta="$(awk -v a="$mval" -v b="$prev" 'BEGIN{printf "%.6g", a-b}')"
  fi
fi

# Session-scoped token + wall sums. Tokens come from the transcript;
# wall comes from (now - first message ts).
tokens=0
wall=0
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
  tokens="$(jq -s 'map((.message.usage.input_tokens // 0) + (.message.usage.output_tokens // 0) + (.message.usage.cache_creation_input_tokens // 0)) | add // 0' "$transcript" 2>/dev/null || echo 0)"
  first_ts="$(jq -s 'map(.timestamp // empty)[0] // empty' "$transcript" 2>/dev/null | tr -d '"')"
  if [ -n "$first_ts" ]; then
    wall="$(awk -v a="$(date -u +%s)" -v b="$(date -u -d "$first_ts" +%s 2>/dev/null || echo 0)" 'BEGIN{print a-b}')"
  fi
fi

jq -nc --arg ts "$ts" --arg slug "$slug" --arg mname "$mname" \
  --argjson mval "${mval:-null}" --arg delta "$delta" \
  --argjson tokens "${tokens:-0}" --argjson wall "${wall:-0}" --arg sid "$sid" \
  '{timestamp:$ts, session_id:$sid, slug:$slug, metric_name:$mname,
    metric_value:$mval, delta_vs_prev:(if $delta=="" then null else ($delta|tonumber) end),
    tokens_spent_this_session:$tokens, wall_seconds_this_session:$wall}' \
  >> "$status_log"

exit 0
