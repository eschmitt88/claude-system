#!/usr/bin/env bash
# PreCompact hook — remind the agent to flush pending findings to disk
# before the conversation is compacted. Compaction loses detail that is
# not written down; this hook makes sure the agent knows to write first.
#
# This hook does not itself write files — it injects a reminder into the
# agent's context. The agent is responsible for actually running /wrap
# or otherwise persisting what matters.
set -euo pipefail

# Swallow stdin payload; we do not currently need its fields.
cat > /dev/null || true

cat <<'EOF'
PreCompact: before compaction, persist anything load-bearing to disk.

- If you are in a research project and have un-logged findings from this
  session, run /wrap to append Did/Findings/Next to NOTES.md now.
- If you generated experiment results that are not yet committed to
  metrics.json or results/, write them.
- Auto-memory is a hint, not a home — promote anything the next session
  must see into a tracked file.
EOF
