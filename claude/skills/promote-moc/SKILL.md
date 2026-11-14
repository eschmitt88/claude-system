---
name: promote-moc
description: Promote a ripe cluster of ≥5 related concepts that no existing MoC covers into mocs/<theme>.md. Declines thin or redundant clusters. Proposes and waits in standard repos; creates, commits and pushes in agency max repos.
respects:
  - ~/claude-system/claude/rules/agency.md
---

# promote-moc

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

Turn an accumulating cluster of concepts into a navigable Map of Content.
`/lint` detects ripe clusters; this creates the MoC.

`/promote-moc [theme]`: force a theme or tag, or with no argument pick the
ripest cluster (or report that none is ripe). Needs a `concepts/`
directory.

## Ripeness

A cluster is ripe only when both hold:

1. **≥5 related concepts** on one coherent theme. Group `concepts/*.md` by
   shared `tags:`, merging near-synonym tags with judgment.
2. **Not already mapped.** No existing `mocs/*.md` covers half or more of
   the cluster. If one does, update that MoC instead, or split it only when
   the sub-theme has clearly outgrown the parent.

If nothing is ripe, say so and stop. A thin or redundant MoC made to have
something to show is worse than none: the value is in real structure, and
an overlapping map costs every later reader.

## Steps

1. **Detect.** List each candidate cluster with its concept count and its
   overlap with existing MoCs, including the ones you decline and why.

2. **Write `mocs/<theme>.md`** from the concept files themselves, not from
   memory, matching an existing MoC in the project if there is one:
   - frontmatter `kind: moc`, `name`, `status: active`, `added: <today>`,
     a `concepts:` list of `[[concepts/<slug>]]` links (each must exist),
     and `tags:` including `moc` and the theme;
   - a framing paragraph: the question this theme answers and why these
     concepts belong together;
   - 2–4 subsections grouping concepts by role, each concept with a
     one-line job and its link, citing the `[[literature/...]]` sources
     that anchor the theme;
   - an open thread or hypothesis, if one is evident.

3. **Backlink**: where concepts carry a `mocs:` field, append
   `[[mocs/<theme>]]`. Don't invent the field.

4. **Index and log**: list the MoC in `_meta/index.md`; append
   `YYYY-MM-DD promote-moc <theme> (<N> concepts)` to `_meta/log.md`.

5. **Persist** (`agency.md`): under `standard`, show the diff and wait.
   Under `max`, commit by path and push. Message:
   `promote-moc YYYY-MM-DD: <theme> (<N> concepts)`.

## Declines are cheap

A decline against a concept set unchanged since the last logged decline
gets one log line, `YYYY-MM-DD promote-moc declined (graph unchanged since
<sha>, N/N concepts mapped)`, and no commit of its own. Write analysis only
when the concept set has changed. (Thirteen consecutive daily declines once
each re-proved the same coverage in a 200-word essay.)
