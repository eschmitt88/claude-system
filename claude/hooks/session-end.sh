#!/usr/bin/env bash
# SessionEnd hook — write a daily session file under the active project's
# journal/ directory as a backstop in case the agent skipped /wrap.
#
# Creates journal/YYYY-MM-DD.md with a minimal header if it does not
# already exist. Appends a one-line session marker with the session_id
# and end time.
set -euo pipefail

# Bounded stdin read: if the harness tears down without delivering/closing
# the payload pipe, a bare `cat` blocks until the hook is cancelled ("Hook
# cancelled" in the CLI output). 2s is orders of magnitude above normal.
payload="$(timeout 2 cat || true)"
cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)"
session_id="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null || true)"
cwd="${cwd:-$PWD}"

dir="$cwd"
root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/CLAUDE.md" ] && [ -d "$dir/_meta" ]; then
    root="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done

[ -z "$root" ] && exit 0

journal="$root/journal"
mkdir -p "$journal"

date_local="$(date +%Y-%m-%d)"
time_local="$(date +%H:%M)"
file="$journal/$date_local.md"

if [ ! -f "$file" ]; then
  cat > "$file" <<EOF
---
kind: journal
date: $date_local
---

# $date_local

EOF
fi

printf -- '- %s session_end session=%s\n' "$time_local" "${session_id:-unknown}" >> "$file"

# NOTE: no session_end line in _meta/log.md. The journal line above is the
# session marker; a tracked-file append at SessionEnd lands after the last
# commit and leaves the repo permanently dirty in non-auto_push projects.

# If the session ended inside an experiment folder whose README.md has
# an unfilled ## Diagnostics section, log a TODO for /lint to surface.
# Non-blocking: just record it, never fail the session.
exp_dir=""
d="$cwd"
while [ "$d" != "$root" ] && [ "$d" != "/" ] && [ -n "$d" ]; do
  case "$d" in
    */experiments/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*)
      exp_dir="$d"
      break
      ;;
  esac
  d="$(dirname "$d")"
done

if [ -n "$exp_dir" ] && [ -f "$exp_dir/README.md" ] && [ -f "$root/_meta/log.md" ]; then
  # "Filled" means the Diagnostics section exists AND
  # intended_effect_confirmed has a non-placeholder value.
  if ! grep -q '^## Diagnostics' "$exp_dir/README.md" 2>/dev/null; then
    printf '%s %s TODO: diagnostics incomplete (missing section) %s\n' \
      "$date_local" "$time_local" "$exp_dir" >> "$root/_meta/log.md"
  elif grep -E '^- intended_effect_confirmed:\s*(<.*>|$)' "$exp_dir/README.md" >/dev/null 2>&1; then
    printf '%s %s TODO: diagnostics incomplete (intended_effect_confirmed unfilled) %s\n' \
      "$date_local" "$time_local" "$exp_dir" >> "$root/_meta/log.md"
  fi
fi

# Commit the daily journal in every git repo — scoped to journal/ so no
# unrelated working-tree state gets swept in. Git is the memory layer;
# a hook-written file nothing commits is leftover dirt (same root cause
# as the old _meta/log.md session_end append). Push immediately:
# committed-but-unpushed is leftover state by this system's rules. A
# failed push self-heals — the next session end commits a new journal
# line and the push retries, carrying anything stranded.
if [ -d "$root/.git" ]; then
  if [ -n "$(git -C "$root" status --porcelain -- journal/ 2>/dev/null)" ]; then
    journal_err="$HOME/.claude/hooks/auto-push.err"
    if git -C "$root" add -- journal/ 2>>"$journal_err" \
       && git -C "$root" commit --quiet -m "journal: session $date_local" -- journal/ 2>>"$journal_err"; then
      if git -C "$root" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
        GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=5" \
          timeout 30 git -C "$root" push --quiet 2>>"$journal_err" || true
      fi
    fi
  fi
fi

# Optional auto-push to the project's git remote. Opt-in only.
# Two opt-in schemas supported:
#   1. Legacy: project.yaml at project root with `auto_push: true` at top level.
#   2. Current: budget.yaml at project root with `git.auto_push: true` (nested).
# Skipped when any experiment is still `status: running` — mid-run state
# is rarely worth pushing.
if [ -d "$root/.git" ]; then
  auto_push=""
  if [ -f "$root/project.yaml" ]; then
    auto_push="$(grep -E '^auto_push:[[:space:]]*true' "$root/project.yaml" 2>/dev/null || true)"
  fi
  if [ -z "$auto_push" ] && [ -f "$root/budget.yaml" ]; then
    auto_push="$(python3 -c '
import sys, yaml
try:
    with open(sys.argv[1]) as f:
        cfg = yaml.safe_load(f) or {}
    if cfg.get("git", {}).get("auto_push") is True:
        print("yes")
except Exception:
    pass
' "$root/budget.yaml" 2>/dev/null || true)"
  fi
  if [ -n "$auto_push" ]; then
    # Skip if any experiment README has status: running in its frontmatter.
    running=""
    shopt -s nullglob
    for rdm in "$root"/experiments/*/README.md; do
      if awk 'BEGIN{in_fm=0} /^---$/{in_fm=!in_fm; next} in_fm && /^status:[[:space:]]*running/{found=1; exit} END{exit !found}' "$rdm" 2>/dev/null; then
        running="$rdm"
        break
      fi
    done
    shopt -u nullglob

    if [ -n "$running" ]; then
      printf '%s %s auto_push skipped (experiment mid-run: %s)\n' \
        "$date_local" "$time_local" "$running" >> "$root/_meta/log.md"
    else
      # Two reasons to engage: uncommitted local work, OR unpushed
      # commits left over from a prior failed push (e.g. transient DNS
      # failure). The retry path is the important one — without it, a
      # failed push leaves HEAD ahead of origin forever unless new
      # work happens to ride along.
      have_changes=0
      if ! git -C "$root" diff --quiet --ignore-submodules --exit-code 2>/dev/null \
         || ! git -C "$root" diff --cached --quiet --ignore-submodules --exit-code 2>/dev/null \
         || [ -n "$(git -C "$root" ls-files --others --exclude-standard 2>/dev/null)" ]; then
        have_changes=1
      fi

      have_unpushed=0
      if git -C "$root" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
        ahead="$(git -C "$root" rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo 0)"
        [ "${ahead:-0}" -gt 0 ] && have_unpushed=1
      fi

      if [ "$have_changes" -eq 1 ] || [ "$have_unpushed" -eq 1 ]; then
        # Append-with-header to a rolling err file. Truncating on every
        # attempt destroyed the diagnostic trail across intermittent
        # failures — now you can read the whole history.
        push_err="$HOME/.claude/hooks/auto-push.err"
        printf '\n=== %s %s %s ===\n' "$date_local" "$time_local" "$(basename "$root")" >> "$push_err" 2>/dev/null || true

        commit_ok=1
        if [ "$have_changes" -eq 1 ]; then
          msg="session: $(date +%F) $(hostname)"
          if ! { git -C "$root" add -A 2>>"$push_err" \
                 && git -C "$root" commit -m "$msg" 2>>"$push_err"; }; then
            commit_ok=0
          fi
        fi

        # Always attempt push if we got here. BatchMode=yes makes ssh
        # fail-fast on locked credentials instead of hanging on a
        # passphrase prompt and getting killed by the hook timeout.
        # `timeout 30` is belt-and-braces for any other network hang.
        # Log only failures. On success the commit hash is the audit
        # record — appending a success line dirties the tree and the
        # next session-end would have stale state to commit.
        push_ok=1
        if [ "$commit_ok" -eq 1 ]; then
          if ! GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=5" \
               timeout 30 git -C "$root" push 2>>"$push_err"; then
            push_ok=0
          fi
        else
          push_ok=0
        fi

        if [ "$push_ok" -ne 1 ]; then
          if [ "$have_changes" -eq 0 ] && [ "$have_unpushed" -eq 1 ]; then
            reason="retry of unpushed commits failed"
          else
            reason="attempted but failed"
          fi
          printf '%s %s auto_push %s (see %s)\n' \
            "$date_local" "$time_local" "$reason" "$push_err" >> "$root/_meta/log.md"
        fi
      fi
    fi
  fi
fi

exit 0
