#!/usr/bin/env bash
# SessionEnd hook — write a daily session file under the active project's
# journal/ directory as a backstop in case the agent skipped /wrap.
#
# Creates journal/YYYY-MM-DD.md with a minimal header if it does not
# already exist. Appends a one-line session marker with the session_id
# and end time.
set -euo pipefail

payload="$(cat || true)"
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

# Also append a one-liner to _meta/log.md for audit.
if [ -f "$root/_meta/log.md" ]; then
  printf '%s %s session_end session=%s\n' "$date_local" "$time_local" "${session_id:-unknown}" >> "$root/_meta/log.md"
fi

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

# Optional auto-push to the project's git remote. Opt-in only:
# requires project.yaml at the project root containing `auto_push: true`.
# Skipped when any experiment is still `status: running` — mid-run state
# is rarely worth pushing.
if [ -f "$root/project.yaml" ] && [ -d "$root/.git" ]; then
  auto_push="$(grep -E '^auto_push:[[:space:]]*true' "$root/project.yaml" 2>/dev/null || true)"
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
      # Only push when there are actual uncommitted changes.
      if ! git -C "$root" diff --quiet --ignore-submodules --exit-code 2>/dev/null \
         || ! git -C "$root" diff --cached --quiet --ignore-submodules --exit-code 2>/dev/null \
         || [ -n "$(git -C "$root" ls-files --others --exclude-standard 2>/dev/null)" ]; then
        msg="session: $(date +%F) $(hostname)"
        if git -C "$root" add -A 2>/dev/null \
           && git -C "$root" commit -m "$msg" 2>/dev/null \
           && git -C "$root" push 2>/dev/null; then
          printf '%s %s auto_push committed+pushed "%s"\n' \
            "$date_local" "$time_local" "$msg" >> "$root/_meta/log.md"
        else
          printf '%s %s auto_push attempted but add/commit/push failed\n' \
            "$date_local" "$time_local" >> "$root/_meta/log.md"
        fi
      fi
    fi
  fi
fi

exit 0
