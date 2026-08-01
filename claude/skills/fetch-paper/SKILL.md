---
name: fetch-paper
description: /fetch-paper <arxiv-id-or-url>. Downloads the full text into raw/papers/<citekey>.pdf (or .md for HTML; GitHub repos land in raw/repos/<repo-slug>.md), derives a Better-BibTeX-style citekey from authors + year, and chains into /ingest to produce the literature note. Handles arxiv abs/pdf URLs, direct PDFs, and GitHub repo READMEs. Does not re-download if the target already exists.
respects:
  - ~/claude-system/claude/rules/evaluation.md
  - ~/claude-system/claude/rules/agency.md
---

# fetch-paper

Pull a primary source into the project's `raw/` tree and hand off to
`/ingest`. The skill is idempotent — running it twice on the same
input leaves the filesystem unchanged the second time.

## Arguments

- `<arxiv-id-or-url>` — one of:
  - arXiv ID: `2506.15692`, `2506.15692v2`
  - arXiv URL: `https://arxiv.org/abs/2506.15692`, `.../pdf/2506.15692`
  - Direct PDF URL
  - GitHub repo URL: `https://github.com/owner/repo`
  - Blog/post URL (HTML)

  Required.

## Steps

1. **Refuse if the cwd is not inside a project.**

2. **Classify the input**:
   - arXiv → target is `raw/papers/<citekey>.pdf`, kind=paper.
   - Direct PDF → target is `raw/papers/<citekey>.pdf`, kind=paper.
   - GitHub repo → target is `raw/repos/<owner>-<repo>.md`, kind=repo.
   - Other HTML → target is `raw/web/<host>-<slug>.md`, kind=post.

3. **Derive the citekey** (for papers):
   - Prefer Better-BibTeX style: `<firstAuthorLastNameLower><year><firstTitleWord>`
     (e.g. `vaswani2017attention`). Fetch the arXiv abs page via
     `WebFetch` to read authors + title + year if not obvious from
     the input. If authors can't be determined, fall back to the
     arXiv ID as citekey (e.g. `arxiv-2506.15692`).
   - Slug non-ASCII down to ASCII; lowercase; strip punctuation.

4. **Check for existence.** If the target file already exists under
   `raw/`, do not re-download. Tell the user the file is already
   present and skip straight to step 6 (ingest).

5. **Download**:
   - arXiv / direct PDF: use `curl -L -o <target> <pdf-url>` via
     Bash. For arXiv, derive the PDF URL from the ID
     (`https://arxiv.org/pdf/<id>.pdf`).
   - GitHub repo: fetch `README.md` via the GitHub API
     (`gh api repos/<owner>/<repo>/readme --jq .content | base64 -d`
     works when `gh` is authenticated; otherwise `curl` the raw
     README at the default branch). Save as Markdown with a short
     YAML header noting the repo URL and fetch date.
   - Blog post / HTML: fetch via `WebFetch` with a prompt that asks
     for the full article body, then write the result as Markdown
     with a header block (source URL, fetched date, title).

6. **Chain into `/ingest`** on the freshly-written `raw/` file. That
   skill produces the `literature/<kind>s/<citekey>.md` note,
   seeds/updates concepts, and logs. Do not duplicate its work here.

7. **Append to `_meta/log.md`**:
   `YYYY-MM-DD HH:MM fetch-paper <input> → <raw-path>`.

8. **Commit the raw fetch.** Agentic workflow — no confirmation
   gate. After the chained `/ingest` completes (or directly after
   step 7 if `/ingest` will run separately), run:

   ```sh
   git add -A
   git commit -m "fetch-paper YYYY-MM-DD: <raw-path>"
   ```

   Then print the commit hash. Note: when `/ingest` is chained,
   it will issue its own commit covering the literature/concept
   updates. The fetch-paper commit covers only the raw addition;
   the two commits together tell the full provenance story.

## Constraints

- Never modify anything already under `raw/`. If you decide the
  existing file is stale, tell the user — they can rename and
  re-fetch.
- Do not write to `literature/`, `concepts/`, or `_meta/index.md`
  directly. Those are `/ingest`'s responsibility.
- Downloads can fail (rate limits, broken URLs). Report the failure
  and stop. Do not swallow errors.

## Notes

- `raw/papers/` is the canonical home for PDFs. Do not invent a
  `raw/arxiv/` or `raw/pdf/` subfolder.
- If the input is a GitHub URL that points at a file inside a repo
  (e.g. `.../blob/main/paper.pdf`), treat it as a direct PDF
  download, not a repo ingest.
- If the same citekey maps to two different papers, append a
  disambiguator (`vaswani2017attention-a`, `-b`) rather than
  overwriting.
