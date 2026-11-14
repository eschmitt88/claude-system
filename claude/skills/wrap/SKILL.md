---
name: wrap
description: End-of-session discipline. Appends today's dated entry (Did / Findings / Next) to NOTES.md, updates _meta/index.md and _meta/log.md, commits and pushes. No confirmation gate.
---

# wrap

Close a work session by committing Did/Findings/Next to `NOTES.md`.

## Steps

Operate on the active project; refuse if the cwd isn't inside one.

1. **Read context**: tail the last 50 lines of `NOTES.md`. If today's
   date (`YYYY-MM-DD` local) already has a heading, append under the
   existing heading's subsections rather than creating a duplicate
   `## YYYY-MM-DD`.

   Also check experiment READMEs touched this session, or marked
   `status: done` / `abandoned`, for placeholder bodies: `Fill in after
   the run`, `Fill after run`, `(post-run)`, `TBD.`, or a heading with
   nothing under it. Name each file and section in chat as a warning and
   fill them in if the experiment did finish. The warning never blocks
   the wrap (the user chose a soft warning), but a `status: done` README
   with an empty `## Result` is a gap someone has to chase later.

2. **Draft the entry** based on the conversation so far:

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

3. **Structured block** (only when the session happened inside an
   experiment folder — i.e. the cwd is at or under
   `experiments/YYYY-MM-DD-<slug>/`). Append a `### Structured`
   subsection beneath `### Next` containing a flat YAML block using
   the **canonical Diagnostics field names from `/implement` step 5**
   (`intended_effect_confirmed`, `leakage_check`,
   `overfitting_signal`, `delta_from_prior`, `unexpected_findings`,
   `next_candidates`) — plain keys, one per line, so the block stays
   greppable. Leave a field as `"unclear"` or `"n/a"` rather than
   omitting it.

   Outside an experiment folder, skip this block.

4. **Update `_meta/index.md`**: if new experiments started or finished,
   reflect that in the "Active experiments" section.

5. **Append to `_meta/log.md`**: one line,
   `YYYY-MM-DD HH:MM wrap <one-line-summary>`.

6. **Write, commit, and push** — an artifact write, no confirmation gate.
   Stage `NOTES.md`, `_meta/index.md` and `_meta/log.md` by path (never
   `git add -A`).

## Why enforce this

The `SessionEnd` hook writes a `journal/YYYY-MM-DD.md` file as a backstop,
but `NOTES.md` is the thing the next session's `SessionStart` hook surfaces.
If you skip `/wrap`, the next session opens blind.
