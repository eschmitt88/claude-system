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

# Transcript aggregates are cumulative per session; every sink must store
# the per-turn DELTA, or summing rows double-counts everything before the
# last turn (measured ~51x; see agentic-research system-proposal
# 2026-07-26-token-metering-cumulative-double-count). Each sink computes
# the delta against its own recorded sum for this session, so each stays
# internally consistent even if the other missed a write.
# tools_used_summary stays cumulative — no consumer sums it, and the delta
# of a histogram isn't worth the complexity.

# 1. Legacy per-project NDJSON log — only when inside a project.
#    Gitignored in projects (appended every turn, so it can never stay
#    committed-clean); /iterate and /lint read it from the local tree.
#    state.db below is the durable copy.
if [ -n "$project_root" ]; then
  ndjson="$project_root/_meta/token_log.ndjson"
  prev='{"input_tokens":0,"output_tokens":0,"cache_read_tokens":0,"cache_creation_tokens":0}'
  if [ -f "$ndjson" ]; then
    prev="$(jq -s --arg s "${session_id:-unknown}" '
      [.[] | select(.session_id==$s)] |
      { input_tokens:          (map(.input_tokens // 0)          | add // 0),
        output_tokens:         (map(.output_tokens // 0)         | add // 0),
        cache_read_tokens:     (map(.cache_read_tokens // 0)     | add // 0),
        cache_creation_tokens: (map(.cache_creation_tokens // 0) | add // 0) }' \
      "$ndjson" 2>/dev/null || printf '%s' "$prev")"
  fi
  delta="$(jq -n --argjson u "$usage" --argjson p "$prev" '
    def d(f): ([($u[f] // 0) - ($p[f] // 0), 0] | max);
    { input_tokens: d("input_tokens"), output_tokens: d("output_tokens"),
      cache_read_tokens: d("cache_read_tokens"),
      cache_creation_tokens: d("cache_creation_tokens"),
      tools_used_summary: ($u.tools_used_summary // {}) }')"
  printf '%s\n' "$(jq -n --arg t "$ts" --arg s "${session_id:-unknown}" --argjson u "$delta" \
    '{timestamp:$t,session_id:$s} + $u')" >> "$ndjson"
fi

# 2. Coordinator state.db — always. Project tag derived from root basename.
project_slug=""
if [ -n "$project_root" ]; then project_slug="$(basename "$project_root")"; fi

COORD_PY="$HOME/claude-system/coordinator/.venv/bin/python"
if [ -x "$COORD_PY" ]; then
  # Pass usage as CLI argv[4], not via stdin. The previous form
  # collided pipe-stdin with heredoc-stdin: the heredoc redirect
  # won, so `sys.stdin.read()` saw "" and every field defaulted to 0.
  "$COORD_PY" - "${session_id:-unknown}" "$project_slug" "$ts" "$usage" <<'PYEOF' || true
import json, sys
from coordinator.db import connect
from coordinator.writers import insert_token_event

FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")
payload = json.loads(sys.argv[4] or "{}")
sid = sys.argv[1] or "unknown"

# Store the per-turn delta vs. what token_events already holds for this
# session. Self-referential, so no schema change: sum(rows) == last
# cumulative once all rows are deltas.
with connect() as c:
    row = c.execute(
        "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
        "       COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_creation_tokens),0)"
        "  FROM token_events WHERE session_id = ?", (sid,)).fetchone()
prev = dict(zip(FIELDS, (int(v or 0) for v in row)))
delta = {}
clamped = []
for f in FIELDS:
    d = int(payload.get(f, 0)) - prev[f]
    if d < 0:
        clamped.append(f)
        d = 0
    delta[f] = d
if clamped:
    # Cumulative transcript total fell below the recorded sum — transcript
    # rotation/truncation, or a resumed session under an old id. Recorded
    # as 0 (under-count, the safe direction); warn so it's diagnosable.
    print(f"WARN token_logger: delta clamped to 0 for {clamped} in session {sid}",
          file=sys.stderr)

insert_token_event(session_id=sid, project=sys.argv[2] or None, **delta,
                   tools_used=payload.get("tools_used_summary", {}),
                   timestamp=sys.argv[3])
PYEOF
fi

exit 0
