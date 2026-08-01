---
name: derive-experiment
description: Turn one literature note into an experiment proposal. Reads the note + frontmatter, extracts the core claim or technique, and proposes an experiment that replicates, tests, or extends that claim in the context of the active project (using the NOTES.md tail and project README.md for framing). Output format matches /propose exactly. Appends the new proposal's slug to the literature note's related_experiments: frontmatter field. Persists per agency.md's Confirmation principle (confirm under standard, auto-advance under max).
respects:
  - ~/.claude/rules/evaluation.md
  - ~/.claude/rules/agency.md
---

# derive-experiment

Bridge from a single paper/repo/post to a testable experiment.

## Arguments

- `<literature-note-path>` — path to a file under `literature/**/*.md`.
  Required. Refuse if the path is outside `literature/` or the file
  lacks a recognized `kind:` (paper | repo | post).

## Steps

1. **Read**, in the active project:
   - the target literature note in full, including frontmatter
   - the project-root `README.md`
   - the last 50 lines of `NOTES.md`
   - any concept files the note wikilinks to (one hop)

2. **Extract the core claim or technique**. One or two sentences. If
   the note has no concrete claim (e.g. a survey with no takeaway
   marked), stop and ask the user to pin down which claim to use.

3. **Decide the experiment mode**:
   - **replicate** — reproduce the paper's headline result on its
     original benchmark.
   - **test** — run the claim against this project's data/setting to
     see if it generalizes.
   - **extend** — combine the technique with something already in this
     project or weaken an assumption.

   State the mode in the rationale. Default to **test** when the
   project has relevant data; default to **replicate** only when the
   paper's claim has never been reproduced in this project.

4. **Produce the proposal** using the exact format `/propose` emits:
   same frontmatter fields (`kind: proposal`, `slug`, `date`,
   `status: proposed`, `hypothesis`, `rationale`, `reads`,
   `expected_metric`, `design_sketch`, `risks`, `related_prior`,
   `estimated_runtime`) and the same prose body. Path:
   `experiments/_proposals/YYYY-MM-DD-<slug>.md`.

   `reads:` must include the source literature note as a wikilink.

5. **Update the literature note's frontmatter**: append the new
   proposal's slug to the `related_experiments:` list (create the
   list if missing). Do not touch any other frontmatter field, and
   do not modify the body of the note.

6. **Persist both files per the Confirmation principle** (`agency.md`):
   a derived proposal is hypothesis selection — show both diffs and
   confirm under `agency: standard`; write and continue under
   `agency: max`.

7. **After writing**, append one line to `_meta/log.md`:
   `YYYY-MM-DD HH:MM derive-experiment <lit-note-path> → <proposal-slug>`.

## Constraints

- This skill produces a proposal only. It does not run
  `/new-experiment`, write code, or spawn a subagent.
- If the claim is too vague to formulate a falsifiable hypothesis, say
  so and stop — don't hand-wave.
- The proposal's `related_prior:` list should include any prior
  experiment in this project that touched the same claim. Grep
  `experiments/*/README.md` frontmatter for matching wikilinks to
  the source note.
