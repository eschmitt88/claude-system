#!/usr/bin/env bash
# smoke.sh — offline smoke tests for the phase-3 scripts.
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

echo
[ "$FAIL" = 0 ] && echo "ALL SMOKE TESTS PASSED" || { echo "SMOKE FAILURES"; exit 1; }
