#!/usr/bin/env bash
# pretooluse_cap.sh — PreToolUse safety net.
#
# If the coordinator has recorded a hard_stop_tokens cap for the current
# session (via `claude-coordinator-job set-cap` or similar), and the
# running total for this session has already exceeded it, emit a blocking
# decision to halt.
#
# Safety net only — the primary controls are /status and /plan consulted
# by the agent. This hook exists so a runaway loop can't drain the quota
# past a declared ceiling.
#
# Payload (Claude Code PreToolUse hook):
#   session_id, cwd, tool_name, tool_input, hook_event_name
#
# If no cap is set, the hook is a no-op (exit 0).
set -euo pipefail

payload="$(cat || true)"
session_id="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null || true)"
[ -z "$session_id" ] && exit 0

COORD_PY="$HOME/claude-system/coordinator/.venv/bin/python"
[ -x "$COORD_PY" ] || exit 0

# Check cap + session-cumulative tokens. If cap exists and burned > cap,
# deny the tool call with a clear reason.
decision="$("$COORD_PY" - "$session_id" <<'PYEOF' 2>/dev/null || echo "")
import sys
from coordinator.db import connect
from coordinator.writers import get_session_cap

sid = sys.argv[1]
cap = get_session_cap(sid)
if cap is None:
    print("")
    raise SystemExit(0)

with connect() as c:
    row = c.execute(
        """
        SELECT COALESCE(SUM(input_tokens + output_tokens + cache_creation_tokens), 0)
          FROM token_events
         WHERE session_id = ?
        """,
        (sid,),
    ).fetchone()
    used = int(row[0] or 0)

if used > cap:
    print(f"HALT:{used}:{cap}")
PYEOF
)"

case "$decision" in
  HALT:*)
    used="${decision#HALT:}"; used="${used%%:*}"
    cap="${decision##*:}"
    # Claude Code expects JSON on stdout to deny a tool call.
    jq -n --argjson used "$used" --argjson cap "$cap" '{
      decision: "deny",
      reason: "coordinator hard-stop: session used \($used) tokens > cap \($cap). Halt chain and investigate."
    }'
    exit 2
    ;;
esac

exit 0
