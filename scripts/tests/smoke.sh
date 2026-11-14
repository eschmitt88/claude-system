#!/usr/bin/env bash
# smoke.sh — offline smoke tests for the scripts, the Stop hook, the
# scaffold, and drift between the system map and the repo.
# Builds a fixture project in a tmpdir, asserts each script's key behaviors.
# Run: bash ~/claude-system/scripts/tests/smoke.sh
set -euo pipefail

PY="$HOME/claude-system/coordinator/.venv/bin/python"
SCRIPTS="$HOME/claude-system/scripts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; FAIL=1; fi; }

# ---- fixture project ----------------------------------------------------
P="$TMP/proj"
mkdir -p "$P"/{_meta,literature/papers,concepts,mocs,raw/_candidates,experiments/_proposals}
cat > "$P/CLAUDE.md" <<'EOF'
# fixture
EOF
cat > "$P/literature/papers/orphan2020paper.md" <<'EOF'
---
kind: paper
relevance: 5
added: "2026-01-01"
related_experiments: []
related_concepts: []
---
# orphan
## Follow-up
- ...
EOF
cat > "$P/concepts/sourceless-idea.md" <<'EOF'
---
kind: concept
sources: []
tags: [demo]
---
# sourceless-idea
See [[missing-target]].
EOF
echo "x" > "$P/raw/_candidates/2026-01-01-old.md"
# stale-candidates is an obligation only in managed (agency: max) repos
echo "agency: max" > "$P/budget.yaml"

# experiments mode + HCE violation fixture
mkdir -p "$P/experiments/2026-01-02-demo"
cat > "$P/experiments/2026-01-02-demo/README.md" <<'EOF'
---
slug: demo
date: "2026-01-02"
status: done
---
# demo
## Diagnostics
- intended_effect_confirmed: yes — it worked great
EOF
cat > "$P/experiments/2026-01-02-demo/log.md" <<'EOF'
10:00 Read test/labels.csv
EOF
echo "seed: 1" > "$P/splits.yaml"

# ---- kg_lint ------------------------------------------------------------
OUT="$("$PY" "$SCRIPTS/kg_lint.py" --root "$P" --json)" && RC=0 || RC=$?
check "kg_lint exits 1 on HCE violation"        "[ $RC -eq 1 ]"
check "kg_lint detects experiments mode"        "echo '$OUT' | grep -q '\"mode\": \"experiments\"'"
check "kg_lint finds orphan"                    "echo '$OUT' | grep -q orphan2020paper"
check "kg_lint finds high-relevance orphan"     "echo '$OUT' | grep -q high_relevance_no_followup"
check "kg_lint finds dead wikilink"             "echo '$OUT' | grep -q missing-target"
check "kg_lint finds sourceless concept"        "echo '$OUT' | grep -q sourceless-idea"
check "kg_lint finds stale candidate"           "echo '$OUT' | grep -q 2026-01-01-old"
check "kg_lint finds unanchored claim"          "echo '$OUT' | grep -q 'worked great'"
check "kg_lint finds tool-log HCE violation"    "echo '$OUT' | grep -q 'tool-log'"

rm "$P/experiments/2026-01-02-demo/log.md" "$P/splits.yaml"
rm -r "$P/experiments/2026-01-02-demo"
OUT2="$("$PY" "$SCRIPTS/kg_lint.py" --root "$P" --json)" && RC2=0 || RC2=$?
check "kg_lint exits 0 in research mode"        "[ $RC2 -eq 0 ]"
check "kg_lint detects research mode"           "echo '$OUT2' | grep -q '\"mode\": \"research\"'"
sed -i 's/agency: max/agency: standard/' "$P/budget.yaml"
OUT3="$("$PY" "$SCRIPTS/kg_lint.py" --root "$P" --json)" || true
check "kg_lint mutes stale candidates in standard"  "! echo '$OUT3' | grep -q '\"stale_candidates\": \[$' || echo '$OUT3' | python3 -c 'import json,sys; r=json.load(sys.stdin); sys.exit(0 if r[\"stale_candidates\"]==[] and r[\"candidates_count\"]==1 else 1)'"

# ---- chain_budget -------------------------------------------------------
cat > "$P/budget.yaml" <<'EOF'
max_tokens: 1000
max_experiments: 5
EOF
cat > "$P/_meta/token_log.ndjson" <<'EOF'
{"timestamp":"2026-01-01T00:00:00Z","session_id":"s","input_tokens":10,"output_tokens":2000,"cache_creation_tokens":0}
EOF
CB="$("$PY" "$SCRIPTS/chain_budget.py" --root "$P" --chain-start 2025-12-31T00:00:00Z)"
check "chain_budget trips max_tokens"           "echo '$CB' | grep -q '\"halt\": true'"
check "chain_budget names the ceiling"          "echo '$CB' | grep -q 'tokens_spent:gte:1000'"
CB2="$("$PY" "$SCRIPTS/chain_budget.py" --root "$P" --chain-start 2026-06-01T00:00:00Z)"
check "chain_budget clean when spend predates chain" "echo '$CB2' | grep -q '\"halt\": false'"
CB3="$("$PY" "$SCRIPTS/chain_budget.py" --root "$P" --chain-start 2026-06-01T00:00:00Z --until experiments_completed:gte:2 --experiments-completed 2)"
check "chain_budget honors --until"             "echo '$CB3' | grep -q '\"halt\": true'"

# ---- new_project --------------------------------------------------------
NP_OUT="$(PROJECTS_ROOT="$TMP/research" TEMPLATE_DIR="$HOME/claude-system/claude/templates/project" \
  bash "$SCRIPTS/new_project.sh" smoke-proj --experiments --no-remote)"
NP="$TMP/research/smoke-proj"
check "new_project scaffolds"                   "[ -f '$NP/CLAUDE.md' ] && [ -d '$NP/_meta' ]"
check "new_project substitutes slug"            "grep -q smoke-proj '$NP/README.md'"
check "new_project makes initial commit"        "git -C '$NP' log --oneline | grep -q scaffold"
check "new_project links experiment skills"     "[ -L '$NP/.claude/skills' ]"
check "new_project refuses duplicate"           "! PROJECTS_ROOT='$TMP/research' TEMPLATE_DIR='$HOME/claude-system/claude/templates/project' bash '$SCRIPTS/new_project.sh' smoke-proj --no-remote 2>/dev/null"

PROJECTS_ROOT="$TMP/research" TEMPLATE_DIR="$HOME/claude-system/claude/templates/project" \
  bash "$SCRIPTS/new_project.sh" smoke-max --agency-max --no-remote >/dev/null
NM="$TMP/research/smoke-max"
check "new_project --agency-max sets agency"    "grep -q '^agency: max' '$NM/budget.yaml'"
check "new_project defaults to standard"        "grep -q '^agency: standard' '$NP/budget.yaml'"
check "new_project fills hardware hints"        "! grep -q 'YOUR_GPU' '$NM/budget.yaml' && ! grep -q 'system_ram_gb: 0\$' '$NM/budget.yaml'"
check "new_project budget.yaml still parses"    "'$PY' -c 'import yaml,sys; d=yaml.safe_load(open(sys.argv[1])); assert isinstance(d[\"hardware\"][\"system_ram_gb\"], int)' '$NM/budget.yaml'"
check "lit-only project has no skills link"     "[ ! -e '$NM/.claude/skills' ]"
# Claude Code reads only `paths:` from a rule's frontmatter; any other key
# (the old `applies_to:`) is ignored and the rule loads in every session.
check "template rules are scoped by paths:"     "for f in '$NM'/.claude/rules/*.md; do grep -q '^paths:' \"\$f\" && ! grep -q '^applies_to:' \"\$f\" || exit 1; done"
check "template CLAUDE.md under 80 lines"       "[ \$(wc -l < '$NM/CLAUDE.md') -le 80 ]"

# ---- token logger (Stop hook) ---------------------------------------------
# One response is written as several transcript records that repeat its usage,
# and a delegating session spends most of its tokens in subagent transcripts.
TH="$TMP/home"; TP="$TMP/tproj"; TR="$TMP/tr"
mkdir -p "$TH/.claude" "$TH/claude-system" "$TP/_meta" "$TR/sess/subagents"
ln -s "$HOME/claude-system/coordinator" "$TH/claude-system/coordinator"
touch "$TP/CLAUDE.md"
"$PY" - "$TR" <<'PYEOF'
import json, sys, pathlib
T = pathlib.Path(sys.argv[1])
def rec(mid, rid, i, o, cc, cr, tool=None):
    content = [{"type": "tool_use", "id": "tu_" + tool, "name": tool}] if tool else [{"type": "text", "text": "x"}]
    return json.dumps({"requestId": rid, "timestamp": "2026-01-01T00:00:00Z", "message": {
        "id": mid, "model": "claude-opus-5-5", "content": content,
        "usage": {"input_tokens": i, "output_tokens": o,
                  "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr}}})
(T / "sess.jsonl").write_text("\n".join([
    rec("m1", "r1", 10, 100, 1000, 5, "Bash"), rec("m1", "r1", 10, 100, 1000, 5),
    rec("m1", "r1", 10, 100, 1000, 5, "Read"), rec("m2", "r2", 1, 20, 0, 7)]) + "\n")
(T / "sess/subagents/agent-a1.jsonl").write_text("\n".join([
    rec("m3", "r3", 2, 300, 50, 0, "Grep"), rec("m3", "r3", 2, 300, 50, 0)]) + "\n")
PYEOF
(cd "$TMP" && HOME="$TH" "$PY" -c "from coordinator.init_db import main; main()" >/dev/null)
TL_PAYLOAD="{\"session_id\":\"S1\",\"transcript_path\":\"$TR/sess.jsonl\",\"cwd\":\"$TP\"}"
tl_run() { echo "$TL_PAYLOAD" | HOME="$TH" bash "$HOME/claude-system/claude/hooks/token_logger.sh"; }
tl_run; tl_run
TL_SUM="$("$PY" - "$TP/_meta/token_log.ndjson" <<'PYEOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
print(len(rows), *(sum(r[k] for r in rows) for k in
      ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")),
      json.dumps(rows[0]["tools_used_summary"], sort_keys=True))
PYEOF
)"
check "token_logger dedupes repeated records and counts subagents" "[ \"\$TL_SUM\" = '2 13 420 1050 12 {\"Bash\": 1, \"Grep\": 1, \"Read\": 1}' ]"
TL_DB="$(sqlite3 "$TH/.claude/state.db" 'select count(*), sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), project from token_events')"
check "token_logger second turn adds a zero delta to state.db"      "[ '$TL_DB' = '2|13|420|1050|tproj' ]"

# ---- system map drift ------------------------------------------------------
# docs/index.html enumerates skills, hooks and CLIs by hand; fail when the
# page and the repo disagree, so the map cannot rot silently.
MAP_OUT="$("$PY" - "$HOME/claude-system" <<'PYEOF'
import re, sys, tomllib, pathlib
R = pathlib.Path(sys.argv[1]); html = (R / "docs/index.html").read_text()
def sect(i):
    return re.search(r'<section id="%s">.*?</section>' % i, html, re.S).group(0)
want_skills = {p.parent.name for g in ("skills", "skills-experiment")
               for p in (R / "claude" / g).glob("*/SKILL.md")}
have_skills = set(re.findall(r'<td class="mono">/([a-z-]+)</td>', sect("skills")))
want_hooks = {p.name for p in (R / "claude/hooks").glob("*.sh")}
have_hooks = set(re.findall(r'<td class="mono">([a-z_-]+\.sh)</td>', sect("hooks")))
want_clis = set(tomllib.loads((R / "coordinator/pyproject.toml").read_text())["project"]["scripts"])
have_clis = set(re.findall(r'<td class="mono">(claude-coordinator-[a-z]+)</td>', sect("coordinator")))
bad = []
for name, want, have in (("skills", want_skills, have_skills), ("hooks", want_hooks, have_hooks), ("clis", want_clis, have_clis)):
    if want != have:
        bad.append(f"{name}: missing from map {sorted(want - have)}, stale in map {sorted(have - want)}")
    kpi = re.search(r'id="kpi-%s">(\d+)<' % name, html)
    if not kpi or int(kpi.group(1)) != len(want):
        bad.append(f"{name}: KPI count {kpi.group(1) if kpi else None} != {len(want)}")
print("; ".join(bad) or "ok")
PYEOF
)"
check "system map lists exactly the skills, hooks and CLIs that exist ($MAP_OUT)" "[ '$MAP_OUT' = ok ]"

echo
[ "$FAIL" = 0 ] && echo "ALL SMOKE TESTS PASSED" || { echo "SMOKE FAILURES"; exit 1; }
