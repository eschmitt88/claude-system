---
name: fetch-paper
description: /fetch-paper <arxiv-id-or-url> downloads a paper, repo README or post into raw/ under a derived citekey, then chains into /ingest. Skips the download if the target already exists.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# fetch-paper

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Pull a primary source into `raw/` and hand it to `/ingest`. Idempotent: a
second run on the same input changes nothing.

## Input → target

| Input | Target | How |
|---|---|---|
| arXiv ID or abs/pdf URL (`2506.15692`, `…v2`) | `raw/papers/<citekey>.pdf` | `curl -L` from `https://arxiv.org/pdf/<id>.pdf` |
| Direct PDF URL (including a GitHub `…/blob/…/x.pdf`) | `raw/papers/<citekey>.pdf` | `curl -L` |
| GitHub repo URL | `raw/repos/<owner>-<repo>.md` | the README (`gh api repos/<owner>/<repo>/readme --jq .content \| base64 -d`, or the raw file), under a short YAML header with the repo URL and fetch date |
| Other HTML | `raw/web/<host>-<slug>.md` | `WebFetch` for the full article body, under a header with source URL, fetch date and title |

**Citekey**: Better-BibTeX style, `<firstauthorlastname><year><firsttitleword>`,
lowercase ASCII, no punctuation (`vaswani2017attention`). Read authors,
title and year from the arXiv abs page if needed. If the authors can't be
determined, use `arxiv-<id>`. If a citekey collides with a different paper,
append `-a`, `-b`.

## Steps

1. If the target already exists, skip the download and say so.
2. Otherwise download. On failure (rate limit, broken URL), report it and
   stop.
3. Append `YYYY-MM-DD fetch-paper <input> → <raw-path>` to
   `_meta/log.md`, then commit the raw file and the log line by path and
   push.
4. Run `/ingest` on the raw file. It writes the literature note and makes
   its own commit.

Nothing already under `raw/` is ever modified. If an existing file looks
stale, say so and leave it. `literature/`, `concepts/` and `_meta/index.md`
are `/ingest`'s to write.
