#!/usr/bin/env bash
# OnFailure= handler for scheduled jobs: push a terse ntfy notice.
# Invoked by scripts/systemd/claude-job-failed@.service with the failed unit
# name as $1. Secret-free: the topic comes from ~/.claude/.env (NTFY_TOPIC,
# optional NTFY_URL). No topic → log only.
set -u
unit="${1:-unknown}"
[ -f "$HOME/.claude/.env" ] && set -a && . "$HOME/.claude/.env" && set +a
last="$(journalctl --user -u "$unit" -n 1 -o cat --no-pager 2>/dev/null | tr -d '\r' | cut -c1-160)"
msg="$unit failed on $(hostname -s). last log line: ${last:-n/a}. journalctl --user -u $unit"
echo "$msg"
[ -z "${NTFY_TOPIC:-}" ] && exit 0
curl -fsS -m 15 -H "Title: job failed: $unit" -d "$msg" "${NTFY_URL:-https://ntfy.sh}/$NTFY_TOPIC" >/dev/null 2>&1 || true
exit 0
