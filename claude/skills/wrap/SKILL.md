---
name: wrap
description: End-of-session discipline. Reads tail of NOTES.md to avoid duplicate date headings, appends today's dated entry with Did/Findings/Next subsections, updates _meta/index.md and _meta/log.md, shows diff, waits for confirmation.
---

# wrap

Close a work session by committing Did/Findings/Next to `NOTES.md`.

## Steps

Operate on the active project; refuse if the cwd isn't inside one.

1. **Read context**: tail the last 50 lines of `NOTES.md`. If today's
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

   **If the session was NOT inside an experiment folder**, skip the
   Structured block entirely. Instead, append one line to
   `_meta/log.md`:
   `YYYY-MM-DD HH:MM wrap-skip-structured reason=<cwd-not-in-experiment>`.

4. **Update `_meta/index.md`**: if new experiments started or finished,
   reflect that in the "Active experiments" section.

5. **Append to `_meta/log.md`**: one line,
   `YYYY-MM-DD HH:MM wrap <one-line-summary>`.

6. **Write the changes, commit, and print the commit hash** — an
   artifact write, so no confirmation gate.

## Why enforce this

The `SessionEnd` hook writes a `journal/YYYY-MM-DD.md` file as a backstop,
but `NOTES.md` is the thing the next session's `SessionStart` hook surfaces.
If you skip `/wrap`, the next session opens blind.
