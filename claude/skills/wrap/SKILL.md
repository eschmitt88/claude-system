---
name: wrap
description: End-of-session discipline. Reads tail of NOTES.md to avoid duplicate date headings, appends today's ## YYYY-MM-DD entry with Did/Findings/Next subsections, updates _meta/index.md and _meta/log.md, shows diff, waits for confirmation.
---

# wrap

Close a work session by committing Did/Findings/Next to `NOTES.md`.

## Steps

1. **Locate the active project**: the current working directory's project
   root (nearest ancestor containing both `CLAUDE.md` and `_meta/`).
   Refuse if no project is found.

2. **Read context**: tail the last 50 lines of `NOTES.md`. If today's
   date (`YYYY-MM-DD` local) already has a heading, append under the
   existing heading's subsections rather than creating a duplicate
   `## YYYY-MM-DD`.

3. **Draft the entry** based on the conversation so far:

   ```markdown
   ## YYYY-MM-DD

   ### Did
   - ...

   ### Findings
   - ...

   ### Next
   - ...
   ```

   Each bullet is specific, past-tense, and names files/experiments
   touched. Empty sections are allowed — better than filler.

4. **Structured block** (only when the session happened inside an
   experiment folder — i.e. the cwd is at or under
   `experiments/YYYY-MM-DD-<slug>/`). Append this directly beneath the
   `### Next` subsection:

   ```markdown
   ### Structured

   ```yaml
   intended_effect: "<what this session was trying to cause>"
   intended_effect_confirmed: <yes | no | partial | unclear>
   diagnostics.leakage_check: "<method — finding, or 'n/a'>"
   diagnostics.overfitting_signal: "<train/val gap — interpretation, or 'n/a'>"
   diagnostics.data_quality_issues: "<one line, or 'none'>"
   delta_from_prior: "<vs <prior-slug>, metric delta and cause>"
   next_candidates:
     - "<one-sentence follow-up 1>"
     - "<one-sentence follow-up 2>"
   ```
   ```

   Keys are **flat** — nested diagnostics use dotted names
   (`diagnostics.leakage_check`, etc.) rather than a nested map, so the
   block stays greppable. Leave a field as `"unclear"` or `"n/a"`
   rather than omitting it.

   **If the session was NOT inside an experiment folder**, skip the
   Structured block entirely. Instead, append one line to
   `_meta/log.md`:
   `YYYY-MM-DD HH:MM wrap-skip-structured reason=<cwd-not-in-experiment>`.

5. **Update `_meta/index.md`**: if new experiments started or finished,
   reflect that in the "Active experiments" section.

6. **Append to `_meta/log.md`**: one line,
   `YYYY-MM-DD HH:MM wrap <one-line-summary>`.

7. **Show the diff** of all modified files and wait for the user to
   confirm before writing. Do not auto-commit to git — the user decides
   when to commit.

## Why enforce this

The `SessionEnd` hook writes a `journal/YYYY-MM-DD.md` file as a backstop,
but `NOTES.md` is the thing the next session's `SessionStart` hook surfaces.
If you skip `/wrap`, the next session opens blind.
