#!/usr/bin/env bash
# PreCompact hook — remind the agent to flush pending findings to disk
# before the conversation is compacted. Compaction loses detail that is
# not written down; this hook makes sure the agent knows to write first.
#
# This hook does not itself write files — it injects a reminder into the
# agent's context. The agent is responsible for actually running /wrap
# or otherwise persisting what matters.
set -euo pipefail

# transcript_path is a common hook-input field (token_logger.sh and
# status_emit.sh read it the same way). Bounded read, as in session-end.sh.
payload="$(timeout 2 cat || true)"
transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null || true)"

cat <<'EOF'
PreCompact: before compaction, persist anything load-bearing to disk.

- If you are in a research project and have un-logged findings from this
  session, run /wrap to append Did/Findings/Next to NOTES.md now.
- If you generated experiment results that are not yet committed to
  metrics.json or results/, write them.
- Auto-memory is a hint, not a home — promote anything the next session
  must see into a tracked file.
EOF

if [ -n "$transcript" ]; then
  cat <<EOF

The full pre-compaction transcript stays on disk at:
  $transcript

Compaction demotes detail; it does not delete it. Write the address with
whatever you persist — cite this path (and the file + heading you wrote to)
so a later turn can recover the exact original instead of trusting the
summary. If after compaction the summary looks like it dropped something,
read this file rather than reconstructing from memory.
EOF
fi
