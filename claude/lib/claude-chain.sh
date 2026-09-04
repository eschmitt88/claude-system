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

claude_chain() {
  local log="$1"; shift
  local models rest i m
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
    local rc=0
    { claude "${args[@]}" "$@" 2>&1 | grep -v 'failed: Hook cancelled' >> "$log"; rc=${PIPESTATUS[0]}; } || true
    if [ "$rc" -eq 0 ]; then
      if ! tail -c "+$((before + 1))" "$log" \
           | grep -qiE "reached your .{0,40}limit|usage limit|out of (usage )?credits"; then
        [ "$i" -eq 0 ] || echo "[claude_chain] fell back to '$m' (primary '${models[0]}' unavailable)" >> "$log"
        return 0
      fi
    fi
    echo "[claude_chain] model '$m' failed or hit its limit; trying next" >> "$log"
  done

  echo "[claude_chain] FAILED on every model in the chain (${CLAUDE_MODELS:-opus,sonnet})" >> "$log"
  return 1
}
