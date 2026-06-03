---
name: discover
description: Web-grounded literature triage. /discover <topic> [--n N] uses WebSearch and WebFetch to surface recent papers, repos, and posts on a topic, then writes a single ranked triage file to raw/_candidates/YYYY-MM-DD-<slug>.md. Each entry has title, URL, source type, one-line summary, and the reasoning for inclusion. Default N=10. Does not fetch full PDFs — /fetch-paper does that.
respects:
  - ~/.claude/rules/evaluation.md
  - ~/.claude/rules/agency.md
---

# discover

Surface candidate reading on a topic. The goal is a short, ranked list
the user can curate — a triage, not a library dump.

Motivated by MLE-STAR (arXiv 2506.15692) and related work finding that
web-retrieval-grounded agents consistently outperform agents relying
only on the LLM's training-time knowledge. The model's priors are
stale; the web is not.

## Arguments

- `<topic>` — free-text topic or question. Required. Quote if
  multi-word.
- `--n <N>` — optional. Maximum entries in the triage file.
  Default **10**.

## Steps

1. **Locate the active project** (nearest ancestor with `CLAUDE.md`
   and `_meta/`). Refuse if none — `discover` writes into a project.

2. **Search**. Use `WebSearch` with one or two focused queries for the
   topic. When a result is plausibly relevant, use `WebFetch` to pull
   enough of the page to write a defensible one-line summary. Prefer
   primary sources (arXiv abstract pages, GitHub READMEs, original
   blog posts) over aggregators.

3. **Rank**. Use your judgment. What matters: recency, fit to the
   stated topic, fit to the project's current direction (skim
   `concepts/`, the last 50 lines of `NOTES.md`, and the most recent
   `experiments/*/README.md` frontmatter before deciding), and
   diversity of viewpoint. No hardcoded scoring formula — decide the
   way a good reviewer would and justify each inclusion in one
   sentence.

4. **Write the triage file** to
   `raw/_candidates/YYYY-MM-DD-<topic-slug>.md`. Create the directory
   if missing. Use this frontmatter (flat YAML):

   ```yaml
   ---
   kind: candidates
   topic: "<topic as given>"
   discovered: YYYY-MM-DD
   source: discover
   n_requested: <N>
   n_returned: <actual count>
   ---
   ```

   Body format — one `##` heading per entry, in rank order:

   ```markdown
   ## 1. <Title>

   - url: <URL>
   - type: paper | repo | post | talk
   - summary: <one sentence>
   - reason: <one sentence on why this made the cut for this project>
   ```

5. **Write the triage file.** Agentic workflow — no confirmation
   gate.

6. **Append to `_meta/log.md`**:
   `YYYY-MM-DD HH:MM discover <topic-slug> n=<count>`.

7. **Commit.** After writing the triage file and the log line, run:

   ```sh
   git add -A
   git commit -m "discover YYYY-MM-DD: <topic-slug> n=<count>"
   ```

   Then print the commit hash. Rationale: git is the memory
   layer per `CLAUDE.md`, and commits are reversible
   (`git revert`).

## What this skill does NOT do

- Does not download full PDFs. That is `/fetch-paper`'s job — the user
  curates this list and then invokes `/fetch-paper` on the entries
  they want to read.
- Does not create literature notes. That happens later via `/ingest`.
- Does not write to `literature/`, `concepts/`, or any experiment
  folder.
- Does not fabricate results. If `WebSearch` returns nothing credible,
  write a candidates file with `n_returned: 0` and say so in the body.

## Notes

- `raw/_candidates/` is a staging area, not permanent storage.
  `/lint` flags candidates files older than 14 days — either curate
  them into `/fetch-paper`-able URLs or delete.
- If `N` is very large, consider delegating the search to the
  Explore agent to keep the main context clean. The triage file is
  still written by the main agent.
