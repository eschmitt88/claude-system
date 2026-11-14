---
name: ingest
description: /ingest <raw-path> turns a file under raw/ into a literature note with relevance and credibility scores, updates or seeds the concepts it raises, and commits. No confirmation gate.
respects:
  - ~/claude-system/claude/rules/agency.md
---

# ingest

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Turn a raw source into a processed literature note and record the concepts
it raises. An unreadable or empty raw file is an abort, not a guess.

## The note

`literature/<kind>s/<name>.md`, from `_meta/templates/<kind>.md`. Kind
follows the path (`raw/papers/` → paper, `raw/repos/` → repo, `raw/web/` →
post) unless the content clearly disagrees.

Read enough of the source to fill TL;DR, claims, methods and results (a
repo: README plus top-level layout; a post: all of it). Fill the
frontmatter the template defines. The fields that need care:

- `source:` the raw path; `added:` today.
- `institutions:` author affiliations as a list. They are in the PDF's
  author block, **not** on the arXiv abstract page, so read the first one
  or two pages (Read's `pages` parameter; if the PDF won't render,
  `uv run --with pypdf python -c "import pypdf;print(pypdf.PdfReader('<path>').pages[0].extract_text())"`).
- `peer_reviewed:` `true` for a peer-reviewed venue, `false` for an arXiv,
  workshop or blog preprint, `unknown` if unclear.
- `code_url:` the released code or artifacts if the source names any.
- `citations:` an integer only if you can establish it; never a guess.
- `relevance:` and `credibility:` per the rubrics below. Put a one-line
  justification under `**Relevance:**` in `## Follow-up` and under
  `**Credibility:**` in `## Trust signals`. The justification is what lets
  the user overrule a score later.

**Relevance** (0–5) is judged against the project's own "What this project
is about". A project may restate this rubric in its `CLAUDE.md`. With no
mission statement, score 0 and say the rubric could not be applied.

| | |
|---|---|
| 5 | Seeds a concept others will rely on, or is the canonical evidence for a load-bearing one |
| 4 | Material new evidence for an existing concept, or seeds one likely to matter soon |
| 3 | Useful prior art on an active theme; cite-worthy, shifts no concept |
| 2 | Adjacent or comparative; informs framing |
| 1 | Tangential; recorded for completeness |
| 0 | Unscored (never a judgment of "tangential"; that is 1) |

**Credibility** (0–5) is independent of relevance. Weight released code
and peer review at least as heavily as the author's institution, which is
a prior and not a verdict.

| | |
|---|---|
| 5 | Top-tier lab or venue, peer-reviewed, code and artifacts released, well cited or reproduced |
| 4 | Strong on most signals, e.g. a major-lab preprint with code |
| 3 | A reputable group or a peer-reviewed venue; partial signals |
| 2 | Preprint from an unknown group, no code, few citations |
| 1 | Unverifiable authorship, no peer review, no code, no citations |
| 0 | Unscored (insufficient information) |

## The graph

- **Concepts.** Extract the 1–5 atomic ideas the source raises. If
  `concepts/` already has one (match names loosely), add this note to its
  `sources:`. Otherwise seed a new file from `_meta/templates/concept.md`.
- **Index.** Note an emerging MoC candidate (≥5 concepts in a cluster) in
  `_meta/index.md`.
- **Log.** Append `YYYY-MM-DD ingest <raw-path>` to `_meta/log.md`.
- **Imports.** Run `/sync-imports`.
- **Commit** and push, staging what you wrote by path (never `git add -A`:
  it sweeps in whatever else is dirty). Message:
  `ingest YYYY-MM-DD: <raw-path> → <literature note>`.
