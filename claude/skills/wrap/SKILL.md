---
name: wrap
description: End-of-session discipline. Reads tail of NOTES.md to avoid duplicate date headings, appends today's dated entry with Did/Findings/Next subsections, updates _meta/index.md and _meta/log.md, shows diff, waits for confirmation.
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

   Also scan recently-touched experiment READMEs for placeholder rot:
   for any `experiments/YYYY-MM-DD-<slug>/README.md` that was modified
   in this session OR whose frontmatter says `status: done` or
   `status: abandoned`, grep the body for placeholder phrases:
   `Fill in after the run`, `Fill after run`, `(post-run)`, `TBD.`
   (with terminal period, to avoid false-positives on "TBD" as part
   of prose), or a section heading followed only by blank lines.

   If any placeholder is found, emit a clear soft warning to the
   user in chat:

   > ⚠ Experiment README has placeholder body content:
   > - experiments/<slug>/README.md: `## Result` still says "Fill in after the run"
   > - experiments/<other>/README.md: `## Diagnostics` still says "TBD"
   >
   > Consider populating before wrap (`/wrap` will proceed anyway).

   This is INFORMATIONAL — do NOT block the wrap. The user opted
   into soft-warning behavior; respect that. But populating the
   bodies before continuing is the right thing to do when the
   experiment actually completed; otherwise the wrap commits a
   `status: done` README with an empty `## Result` section, which
   future readers (or `/lint`) will then have to chase down.

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

7. **Write the changes and commit.** This is an agentic workflow:
   skip the human confirmation gate. After writing all the files,
   run:

   ```sh
   git add -A
   git commit -m "wrap YYYY-MM-DD: <one-line summary from step 6>"
   ```

   Then print the new commit hash. Rationale: git is the memory
   layer per `CLAUDE.md`, and commits are reversible (`git revert`
   or `git reset --soft HEAD~1`), so the default is to commit
   rather than leave the working tree dirty. The user can amend,
   split, or revert after the fact if needed.

## Why enforce this

The `SessionEnd` hook writes a `journal/YYYY-MM-DD.md` file as a backstop,
but `NOTES.md` is the thing the next session's `SessionStart` hook surfaces.
If you skip `/wrap`, the next session opens blind.
