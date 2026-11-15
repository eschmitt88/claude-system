#!/usr/bin/env bash
# claude_chain — run `claude -p` down a pinned model pecking order.
#
# Why: without an explicit --model, `claude -p` inherits whatever interactive
# default sits in ~/.claude/settings.json. A human running /model then silently
# repoints every unattended cron. That is not hypothetical — a model whose
# allotment had run out was the inherited default here on 2026-08-16, and
# three consecutive runs of a scheduled job died before anyone noticed.
#
# A usage-limit hit is deliberately awkward to detect: the CLI exits non-zero
# with an EMPTY stderr and puts the cause on stdout ("You've reached your
# <model> limit."), and the same notice can arrive with exit 0. So match the
# text as well as the exit code.
#
# --fallback-model is passed too, but not trusted alone: it is documented for
# "overloaded or not available", while allotment exhaustion kills the process.
#
# Usage:  claude_chain <logfile> <claude-arg>...
#   e.g.  claude_chain _meta/digest.log --permission-mode bypassPermissions "/digest"
# Env:    CLAUDE_MODELS  comma-separated chain (default "opus,sonnet")
# Returns 0 if any model completed, 1 if the whole chain failed.

# Redaction for logs that land in (often public) repos. The patterns are
# machine-private — they ARE the identifiers — so they live outside this
# repo in ~/.config/claude-redact.sed (a sed -E script, one s### per
# line). Without it, only $HOME is rewritten to "~".
_claude_chain_redact() {
  local f="${CLAUDE_REDACT_SED:-$HOME/.config/claude-redact.sed}"
  if [ -r "$f" ]; then
    sed -u -E -e "s#${HOME}#~#g" -f "$f"
  else
    sed -u -e "s#${HOME}#~#g"
  fi
}

# claude_alert <key> <title> <body> — push a failure notice (ntfy).
#
# Why: a cron run that fails says so only in a log nobody is reading. The
# 2026-11-09 weekly digest died on an expired login and went unnoticed for
# six days. systemd jobs have claude-job-failed@.service; cron wrappers call
# this instead.
#
# Topic from NTFY_TOPIC (env, else ~/.claude/.env), server from NTFY_URL
# (default https://ntfy.sh). No topic => silent no-op. At most one push per
# <key> per day, so an expired login alerts once, not once per repo.
# The body is fixed text chosen by the caller: never log content, which can
# name hosts and private projects.
claude_alert() {
  local key="$1" title="$2" body="$3"
  local topic="${NTFY_TOPIC:-}" url="${NTFY_URL:-}" envf="$HOME/.claude/.env"
  if [ -z "$topic" ] && [ -r "$envf" ]; then
    topic="$(sed -n 's/^NTFY_TOPIC=//p' "$envf" | tail -n1 | tr -d "\"'")"
    [ -n "$url" ] || url="$(sed -n 's/^NTFY_URL=//p' "$envf" | tail -n1 | tr -d "\"'")"
  fi
  [ -n "$topic" ] || return 0
  local stamp="${CLAUDE_STATE_DIR:-$HOME/.claude/state}/alert-$key" today
  today="$(date +%F)"
  [ "$(cat "$stamp" 2>/dev/null)" = "$today" ] && return 0
  mkdir -p "$(dirname "$stamp")" 2>/dev/null && printf '%s\n' "$today" > "$stamp"
  curl -fsS -m 15 -H "Title: $title" -d "$body" "${url:-https://ntfy.sh}/$topic" >/dev/null 2>&1 || true
}

claude_chain() {
  local log="$1"; shift
  local models rest i m reason=error
  IFS=',' read -r -a models <<< "${CLAUDE_MODELS:-opus,sonnet}"

  for i in "${!models[@]}"; do
    m="${models[$i]}"
    rest=$(IFS=,; echo "${models[*]:$((i+1))}")

    local args=(-p --model "$m")
    [ -n "$rest" ] && args+=(--fallback-model "$rest")

    # Only inspect the bytes THIS attempt appends. Scanning the whole log tail
    # would re-match an earlier attempt's limit notice and discard a good run.
    local before=0
    [ -f "$log" ] && before=$(wc -c < "$log")

    # Filter the CLI's SessionEnd-hook teardown notice ("... failed: Hook
    # cancelled") before it lands in what is usually a *tracked* log — it
    # leaked into four repos' _meta/*.log and was hand-reverted 7+ times.
    # PIPESTATUS[0] preserves claude's own exit code through the filter.
    # The output also passes through the machine-private redaction script
    # (see _claude_chain_redact): these logs are usually tracked in public
    # repos, and a session's prose names hosts, home paths and addresses.
    local rc=0
    { claude "${args[@]}" "$@" 2>&1 | grep --line-buffered -v 'failed: Hook cancelled' \
        | _claude_chain_redact >> "$log"; rc=${PIPESTATUS[0]}; } || true
    if [ "$rc" -eq 0 ]; then
      if ! tail -c "+$((before + 1))" "$log" \
           | grep -qiE "reached your .{0,40}limit|usage limit|out of (usage )?credits"; then
        [ "$i" -eq 0 ] || echo "[claude_chain] fell back to '$m' (primary '${models[0]}' unavailable)" >> "$log"
        return 0
      fi
    fi
    # Classify this attempt from the bytes it appended. Auth outranks the
    # rest: an expired login fails every model the same way.
    if tail -c "+$((before + 1))" "$log" | grep -qiE "failed to authenticate|claude auth login"; then
      reason=auth
    elif [ "$reason" != auth ] && tail -c "+$((before + 1))" "$log" \
         | grep -qiE "reached your .{0,40}limit|usage limit|out of (usage )?credits"; then
      reason=limit
    fi
    echo "[claude_chain] model '$m' failed or hit its limit; trying next" >> "$log"
  done

  echo "[claude_chain] FAILED on every model in the chain (${CLAUDE_MODELS:-opus,sonnet})" >> "$log"
  local project what="${*: -1}"
  project="$(basename "$PWD")"
  case "$reason" in
    auth)  claude_alert chain-auth "Scheduled Claude runs: login expired" \
             "$what in $project did not run. The login used by scheduled runs has expired; run 'claude auth login' on the box. Other scheduled runs will fail the same way until then." ;;
    limit) claude_alert chain-limit "Scheduled Claude run: usage limit" \
             "$what in $project did not run: every model in the chain (${CLAUDE_MODELS:-opus,sonnet}) is at its usage limit." ;;
    *)     claude_alert "chain-error-$project" "Scheduled Claude run failed" \
             "$what in $project failed on every model in the chain. See $log in that project." ;;
  esac
  return 1
}
