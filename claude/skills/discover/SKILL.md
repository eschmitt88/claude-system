---
name: discover
description: Web-grounded literature triage. /discover <topic> [--n N] searches for recent papers, repos and posts on a topic and writes one ranked candidates file to raw/_candidates/. Does not fetch or ingest.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# discover

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Triage a topic into a short ranked list for `/curate` (or the user) to act
on. It is web-grounded on purpose: the model's priors are stale, the web is
not.

`/discover <topic> [--n N]`, inside a project. `N` caps the entries
(default 10).

## Output

`raw/_candidates/YYYY-MM-DD-<topic-slug>.md`:

```markdown
---
kind: candidates
topic: "<topic as given>"
discovered: YYYY-MM-DD
source: discover
n_requested: <N>
n_returned: <actual count>
---

## 1. <Title>

- url: <URL>
- type: paper | repo | post | talk
- summary: <one sentence>
- reason: <one sentence on why this made the cut for this project>
- verified: page | snippet
```

One `##` block per entry, in rank order. The dashboard parses this shape.

- **Search** with one or two focused queries and fetch a page when a result
  looks relevant. Prefer primary sources (arXiv abstract pages, READMEs,
  original posts) over aggregators.
- **`verified`** says whether you read the page or only a search snippet.
  Snippet-only numbers and arXiv IDs are often wrong, and `/curate`
  re-checks those entries.
- **Rank** as a good reviewer would: recency, fit to the topic, fit to the
  project's direction (skim `concepts/`, the tail of `NOTES.md`, recent
  experiment READMEs), diversity of viewpoint.
- If nothing credible turns up, still write the file with `n_returned: 0`
  and say so in the body.

Append `YYYY-MM-DD discover <topic-slug> n=<count>` to `_meta/log.md`.
Commit and push, staging what you wrote by path (never `git add -A`: it sweeps in whatever else is dirty). When several `/discover` runs share a repo at once, the caller
commits for all of them (parallel commits race on the index).

## Scope

Write only the candidates file and the log line. Fetching is
`/fetch-paper`, notes are `/ingest`, closing the file is `/curate`. In an
`agency: standard` repo the file creates no obligation; only `agency: max`
repos track and drain the backlog.
