---
name: wrap
description: End-of-session discipline. Appends today's Did / Findings / Next entry to NOTES.md, updates _meta/index.md and _meta/log.md, commits and pushes. No confirmation gate.
---

# wrap

Close a work session in the active project by recording it in `NOTES.md`.
The next session's SessionStart hook shows the tail of that file, so a
skipped wrap means the next session opens blind.

## Steps

1. **Read the tail of `NOTES.md`.** If today's `## YYYY-MM-DD` heading
   exists, append under it; never create a second one.

2. **Write the entry** from the session:

   ```markdown
   ## YYYY-MM-DD

   ### Did
   ### Findings
   ### Next
   ```

   Bullets are specific and past-tense, and name the files and experiments
   touched. An empty section is better than filler. The dashboard and the
   Pages viewer parse the dated heading.

3. **Inside an experiment folder only**, add a `### Structured` block
   under `### Next`: flat YAML with the Diagnostics field names from
   `/implement` (`intended_effect_confirmed`, `leakage_check`,
   `overfitting_signal`, `delta_from_prior`, `unexpected_findings`,
   `next_candidates`), using `"unclear"` or `"n/a"` rather than omitting a
   field.

4. **Check for placeholder rot.** In experiment READMEs touched this
   session, or marked `status: done` / `abandoned`, look for `Fill in after
   the run`, `(post-run)`, `TBD.` or a heading with nothing under it. Fill
   them in if the experiment did finish; otherwise name each file and
   section as a warning. The warning never blocks the wrap.

5. **Update `_meta/index.md`** if experiments started or finished, and
   append `YYYY-MM-DD wrap <one-line-summary>` to `_meta/log.md`.

6. **Commit and push** `NOTES.md`, `_meta/index.md` and `_meta/log.md` by
   path (never `git add -A`).
