---
name: ingest
description: Ingest a file in raw/ into the knowledge graph. Writes literature/<kind>s/<filename>.md from the matching _meta/templates/ template, updates or seeds the concepts it raises, updates index + log, and commits. No confirmation gate.
respects:
  - ~/claude-system/claude/rules/agency.md
---

# ingest

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Turn a raw source into a processed literature note and seed any concepts
it raises.

## Arguments

- `<path>` — path to the file under `raw/`. Required.

## Steps

1. **Classify the kind**: infer from the path.
   - `raw/papers/*` → `paper`
   - `raw/repos/*` → `repo`
   - `raw/web/*`   → `post`
   Override if the content clearly disagrees.

2. **Read the raw source**. For PDFs, extract enough to fill TL;DR, claims,
   methods, results. For repos, scan README + top-level layout. For posts,
   read the whole thing.

3. **Write the processed note** at
   `literature/<kind>s/<safe-filename>.md` using the matching template
   from `_meta/templates/<kind>.md`. Pre-fill:
   - `source:` → the raw path.
   - `added:` → today's date.
   - `title`/`name`, `authors`, `year`, `venue`, `url` where visible.
   - `relevance:` → propose a 0–5 score per the rubric below, with a
     one-line justification in the `## Follow-up` section under the
     heading `**Relevance:**`.
   - `tags:` suggested from content.
   - **Trust signals** (papers/repos) → fill these credibility fields,
     extracted from the source itself where possible:
     - `institutions:` → author affiliations as a list (e.g.
       `["Google DeepMind", "MIT"]`), read from the paper's first page /
       author block. The single biggest "who's behind this" signal.
       Affiliations live in the PDF, **not** the arXiv abstract page, so
       read the PDF's first 1–2 pages (the Read tool's `pages` param;
       poppler is installed). If a PDF still won't render, fall back to
       `uv run --with pypdf python -c "import pypdf;print(pypdf.PdfReader('<path>').pages[0].extract_text())"`.
       Don't leave `institutions: []` when the PDF has the affiliations.
     - `peer_reviewed:` → `true` if published at a peer-reviewed venue,
       `false` for an arXiv / workshop / blog preprint, `unknown` if
       unclear from the source.
     - `code_url:` → link to released code or artifacts if the source
       names one (GitHub, project page); else leave null.
     - `citations:` → integer only if you can establish it (e.g. a
       Semantic Scholar lookup via `WebFetch`); otherwise leave null —
       never guess a count.
     - `credibility:` → a 0–5 composite per the rubric below, with a
       one-line justification under `**Credibility:**` in the
       `## Trust signals` section.

   **Relevance rubric** (project-specific; read the active project's
   `CLAUDE.md` "What this project is about" section to ground the
   scoring — the rubric below is calibrated for the agentic-research
   meta project and other projects should restate the rubric in their
   own CLAUDE.md if they want different semantics):

   - **5** — directly seeds a new concept that downstream projects
     will import; or provides the canonical evidence anchoring an
     existing load-bearing concept.
   - **4** — strengthens an existing concept with material new
     evidence/ablations, or seeds a concept likely to be imported soon.
   - **3** — useful prior art on an active theme but doesn't shift
     any concept; cite-worthy.
   - **2** — adjacent / comparative; informs framing but not
     architecture.
   - **1** — tangential; recorded for completeness.
   - **0** — reserved for "unscored" (do not auto-assign 0; if the
     paper is genuinely tangential, score 1).

   Scores are best-effort and the recorded justification is what lets
   the user overrule them later. If the active project has no clear
   mission statement in its `CLAUDE.md`, default to `relevance: 0` and
   say the rubric could not be applied.

   **Trust-signal rubric** — `credibility` is *independent of
   `relevance`*: a highly relevant paper can be low-credibility (an
   independent preprint with no code) and a low-relevance paper can be
   high-credibility. Score what the evidence supports:

   - **5** — top-tier lab/venue, peer-reviewed, code + artifacts
     released, well cited or independently reproduced.
   - **4** — strong on most signals (e.g. a major-lab preprint with
     code, not yet peer-reviewed).
   - **3** — solid: a reputable group **or** a peer-reviewed venue;
     partial signals.
   - **2** — mixed: preprint from an unknown group, no code, few citations.
   - **1** — weak: independent/unverifiable authorship, no peer review,
     no released code, no citations.
   - **0** — unscored (insufficient information).

   Institution is a *prior, not a verdict* — weight reproducibility
   (released code/artifacts) and peer review at least as heavily as the
   author's affiliation.

4. **Candidate concepts**: extract 1–5 atomic ideas the source raises.
   For each, check `concepts/` for an existing file by name (case- and
   punctuation-insensitive match). If it exists, add the literature
   note to its `sources:`. Otherwise seed a new concept file from
   `_meta/templates/concept.md`.

5. **Update `_meta/index.md`** if a new MoC candidate is emerging
   (≥5 concepts in a cluster).

6. **Append to `_meta/log.md`**: `YYYY-MM-DD HH:MM ingest <raw-path>`.

7. **Run `/sync-imports`** so hub concepts this project declares gain
   their `used_by:` back-references.

8. **Commit** — an artifact write, no confirmation gate. Stage the
   files this skill wrote by path (never `git add -A`: it sweeps in
   whatever else is dirty), commit, and push. Message:
   `ingest YYYY-MM-DD: <raw-path> → <literature note>`.

## Notes

- Never modify `raw/` itself. Treat it as read-only.
- If the file under `raw/` is empty or unreadable, abort and tell the user.
