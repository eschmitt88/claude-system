---
name: lint
description: Knowledge-graph health check. Runs scripts/kg_lint.py (deterministic checks — orphans, dead wikilinks, sourceless concepts, staleness, missing diagnostics, unanchored claims, HCE test/ access), then interprets and prioritizes the findings. Auto-detects research vs experiments mode. Report-only — does not auto-fix. Hard failure on HCE violations.
respects:
  - ~/claude-system/claude/rules/evaluation.md
---

# lint

Surface knowledge-graph rot and HCE-rule violations.

## How

Run the mechanical checks:

```bash
~/claude-system/coordinator/.venv/bin/python \
  ~/claude-system/scripts/kg_lint.py [--root <project>] [--json]
```

The script auto-detects the project mode (research vs experiments, and
whether HCE is active), runs only the checks that apply, and exits 1 on
any HCE violation. Check definitions, thresholds, and the engagement
rule live in the script — edit them there, with the smoke test
(`scripts/tests/smoke.sh`) alongside.

## Your job after the script runs

The script reports; you judge:

- **Prioritize.** Lead with anything high-leverage (high-relevance
  orphans, HCE violations); drop or dismiss noise (e.g. a "dead
  wikilink" that is prose mentioning wikilink syntax, not a real link).
- **MoC calls.** The script emits cluster stats only. A cluster with
  ≥5 concepts, no MoC, and low existing-MoC coverage is a `/promote-moc`
  candidate; a cluster already covered but accreting near-duplicates is
  a consolidation signal for a human to merge/retire — flag, don't
  promote. (Full merge/split detection deferred; see agentic-research
  `docs/system-proposals/2026-06-28-lint-consolidation-check.md`.)
- **Suggest the next action** per finding: link it, `/curate` it,
  implement it, or lower `relevance:` and move on.

## HCE violations

`HCE VIOLATION (HARD)` findings block further `/iterate` cycles until
resolved — never downgrade them to warnings
(`~/claude-system/claude/rules/evaluation.md`).

## Notes

- Read-only. Run weekly, or before `/wrap` at the end of a big push.
- In research-only projects a noisy report usually means the engagement
  definition in the script is the lever to revisit.
