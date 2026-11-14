---
name: lint
description: Knowledge-graph health check. Runs scripts/kg_lint.py (orphans, dead wikilinks, sourceless concepts, staleness, missing diagnostics, unanchored claims, HCE test/ access) and prioritizes the findings. Report-only. HCE violations are hard failures.
respects:
  - ~/claude-system/claude/rules/evaluation.md
---

# lint

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

```bash
~/claude-system/coordinator/.venv/bin/python \
  ~/claude-system/scripts/kg_lint.py [--root <project>] [--json]
```

The script detects the project's mode (research or experiments, HCE or
not), runs the checks that apply, and exits 1 on any HCE violation. Check
definitions and thresholds live in the script, with a smoke test beside it
(`scripts/tests/smoke.sh`). The script reports; you judge:

- **Prioritize.** Lead with HCE violations and high-relevance orphans, and
  dismiss noise.
- **MoC calls.** The script gives cluster stats only. A cluster of ≥5
  concepts with no MoC and low coverage is a `/promote-moc` candidate. A
  covered cluster that keeps accreting near-duplicates is a consolidation
  signal for a human: flag it, don't promote.
- **Rule consistency.** If any loaded instruction file changed since the
  last lint run (user and project `CLAUDE.md`, `.claude/rules/*`,
  `budget.yaml`, the framework rules), read the set as one policy and flag
  contradictions, a contract stated in more than one place (name the file
  that should own it), and references that don't resolve. Skip silently
  when nothing changed.
- **Next action** per finding: link it, `/curate` it, implement it, or
  lower `relevance:` and move on.

`HCE VIOLATION (HARD)` findings block further `/iterate` cycles until
resolved. Never downgrade them to warnings.

Read-only. Run weekly, or before `/wrap` at the end of a big push.
