#!/usr/bin/env bash
# statusline.sh — Claude Code statusLine command.
#
# Besides printing the status line, it records Anthropic's own plan
# utilisation, which Claude Code passes here (Pro/Max, interactive
# sessions, after the session's first API response):
#   .rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}
# The coordinator (coordinator/ratelimits.py) anchors its quota % on it
# and calibrate.py refits the plan ceilings from the log.
#
#   ~/.claude/state/rate-limits.json    newest reading per window
#   ~/.claude/state/rate-limits.ndjson  one line per changed reading
#
# A reading is stamped with the mtime of the session's transcript (≈ its
# last API response), and a stored reading is replaced only by one at
# least as new. An idle session re-rendering old numbers therefore never
# overwrites a busy session's fresh ones, while genuine drops (resets,
# bonus grants) are accepted as the newest truth.
#
# Runs after every response in every interactive session: jq only, no
# python/ccusage, and it never fails the status line.
set +e
umask 077

payload="$(cat)"
state_dir="${CLAUDE_STATE_DIR:-$HOME/.claude/state}"
state="$state_dir/rate-limits.json"
log="$state_dir/rate-limits.ndjson"

if printf '%s' "$payload" | jq -e '.rate_limits | objects' >/dev/null 2>&1; then
  transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty')"
  observed_at="$(stat -c %Y "$transcript" 2>/dev/null || date +%s)"
  mkdir -p "$state_dir" && chmod 700 "$state_dir"
  (
    umask 077
    flock -w 2 9 || exit 0
    [ -s "$state" ] && jq -e . "$state" >/dev/null 2>&1 || echo '{}' > "$state"
    # Emits the new state on line 1, then one log line per changed window.
    out="$(printf '%s' "$payload" | jq -c --slurpfile st "$state" \
      --argjson obs "$observed_at" --arg now "$(date +%s)" '
      . as $p
      | ($st[0] // {}) as $s
      | [ ("five_hour", "seven_day") as $w
          | $p.rate_limits[$w]
          | select(type == "object" and (.used_percentage | type) == "number"
                   and (.resets_at | type) == "number")
          | {window: $w, used_pct: .used_percentage, resets_at: .resets_at,
             observed_at: $obs, session_id: ($p.session_id // null)}
          | select(.observed_at >= ($s[$w].observed_at // 0))
          | select(.used_pct != $s[$w].used_pct or .resets_at != $s[$w].resets_at
                   or ($s[$w].observed_at // 0) < .observed_at)
        ] as $new
      | ($s + ($new | map({key: .window, value: (del(.window))}) | from_entries)
           + {updated_at: ($now | tonumber)}),
        ($new[] | select(.used_pct != $s[.window].used_pct
                         or .resets_at != $s[.window].resets_at)
                | {ts: ($now | tonumber)} + .)
    ' 2>/dev/null)"
    if [ -n "$out" ]; then
      # Log before swapping state: if Claude Code cancels us in between,
      # the next run re-logs the reading rather than silently losing it.
      printf '%s\n' "$out" | tail -n +2 >> "$log"
      printf '%s\n' "$out" | head -n1 > "$state.tmp" && mv -f "$state.tmp" "$state"
    fi
  ) 9>"$state_dir/rate-limits.lock"
fi

# Status line: model · ctx · 5h % → reset · week % → reset. Quota figures
# come from the newest stored reading (any session), not this session's
# possibly older copy; windows whose reset has passed are dropped.
stored="$(cat "$state" 2>/dev/null)"
printf '%s' "$payload" | jq -r --argjson st "${stored:-null}" --arg now "$(date +%s)" '
  def hm: strflocaltime("%H:%M");
  def dhm: strflocaltime("%a %H:%M");
  def win($w):
    ([($st // {})[$w] | objects | {p: .used_pct, r: .resets_at}]
     + [.rate_limits[$w]? | objects | {p: .used_percentage, r: .resets_at}])
    | map(select((.r | type) == "number" and .r > ($now | tonumber)))
    | first // empty;
  [ (.model.display_name // empty),
    (.context_window.used_percentage // empty | "ctx \(floor)%"),
    (win("five_hour") | "5h \(.p | round)%→\(.r | hm)"),
    (win("seven_day") | "wk \(.p | round)%→\(.r | dhm)")
  ] | join(" · ")
' 2>/dev/null || echo "claude"
exit 0
