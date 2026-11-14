---
name: derive-experiment
description: /derive-experiment <literature-note> turns one literature note into an experiment proposal that replicates, tests or extends its core claim in this project, in /propose's format, and back-links the proposal into the note.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# derive-experiment

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

The bridge from one paper, repo or post to a testable experiment. It
writes a proposal only: no scaffolding, no code, no subagent.

`<literature-note-path>` must be under `literature/` with `kind:` paper,
repo or post.

1. **Read** the note in full, the project `README.md`, the tail of
   `NOTES.md`, and the concepts the note links to.

2. **State the core claim or technique** in a sentence or two. If the note
   has no concrete claim, or it is too vague to make falsifiable, stop and
   ask which claim to use.

3. **Choose the mode** and say so in the rationale:
   - **test** the claim on this project's data or setting (the default
     when the project has relevant data);
   - **replicate** the headline result on its original benchmark (only
     when the claim has never been reproduced here);
   - **extend** it by combining it with something already here or
     weakening an assumption.

4. **Write the proposal** exactly as `/propose` does (same frontmatter,
   same prose body, same path). `reads:` includes the source note.
   `related_prior:` lists any earlier experiment here that touched the
   same claim.

5. **Back-link**: append the proposal's slug to the note's
   `related_experiments:`. Change nothing else in the note.

6. **Persist** both files per the Confirmation principle (`agency.md`):
   confirm under `agency: standard`, continue under `agency: max`. Then
   append `YYYY-MM-DD derive-experiment <note-path> → <proposal-slug>`
   to `_meta/log.md`.
