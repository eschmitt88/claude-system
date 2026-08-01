---
name: elevate
description: Evaluate whether ideas in the agentic-research knowledge graph should be adopted into claude-system itself (skills / hooks / rules / settings). For each idea that clears a high reputability-of-evidence bar AND a simplicity bar, write a proposal that makes the case and elevates it for human review under docs/system-proposals/. Never edits claude-system; never applies a change. Most cycles correctly produce zero proposals.
respects:
  - ~/claude-system/claude/rules/agency.md
---

# elevate

The `agentic-research` repo is research-about-research: it curates
literature and concepts on how autonomous research agents are built. Some
of those findings are about exactly the kind of system *this box runs* —
the skills, hooks, and rules in `~/claude-system`. When a curated idea is
both **well-evidenced** and **simplifying**, it should be surfaced as a
candidate improvement to the system itself.

This skill is the bridge. It reads the knowledge graph, compares it against
the live `claude-system`, and writes **proposals for a human to review**.
It is the meta-repo's counterpart to `/derive-experiment`: where that turns
a literature note into a *downstream experiment*, this turns a
well-attested concept into a *candidate change to the harness*.

**It never edits `~/claude-system` and never applies a change.** The only
output is proposal files in this repo. A human accepts or rejects; if
accepted, the human (or a later, explicitly-authorized session) makes the
edit. This separation is the whole point — the system changes only under
human review.

## Scope

- Run only inside the `agentic-research` meta repo (it has `concepts/` and
  the import contract in its `CLAUDE.md`). Refuse elsewhere.
- Targets of a proposal are files under `~/claude-system/claude/`:
  `skills/*/SKILL.md`, `rules/*.md`, `hooks/*.sh`, `settings.json`,
  `CLAUDE.md`. Read them to ground every proposal in what already exists.

## The two gates — both must pass

A candidate idea becomes a proposal only if it clears **both** gates. When
in doubt, do not propose. A cycle that yields zero proposals is the normal,
healthy outcome — restraint is the feature, not a failure (cf.
`/promote-moc`'s decline behavior).

### Gate 1 — Reputable evidence

The idea must be anchored by sources the project itself rates as credible,
not a single weak preprint. Require **at least one** of:

- a **peer-reviewed** source (`peer_reviewed: true`), or
- a source with **released code / artifacts** (`code_url` set), or
- **three or more independent attestations** of the concept across distinct
  groups,

**and** the supporting notes' `credibility:` scores are **>= 3** on
balance. Cite the specific citekeys and why they are reputable. An idea
resting only on `credibility <= 2` preprints does not pass — record it as
considered-and-held, do not write it up.

### Gate 2 — Simplicity

Simplicity is a first-class acceptance criterion, not a tiebreaker. Judge
the change by its effect on the system's total surface area:

- **Strongly prefer** changes that *remove*, *consolidate*, or *clarify* —
  delete a redundant step, merge two skills, tighten a rule, simplify a
  hook. These can pass on a modest evidence base because the downside is low.
- A change that **adds** surface area (a new skill, a new hook, a new rule,
  a new config knob) must clear a higher bar: state plainly what complexity
  it adds, why a *simpler* form (an extra sentence in an existing skill, a
  one-line rule amendment) will not do, and why the benefit is worth the
  permanent maintenance cost. Default to rejecting net-new complexity.
- If the idea can be expressed as a small edit to an existing file rather
  than a new file, propose the small edit.

The simplest viable form of an idea is the one to propose. If the only
viable form is complex, that is itself a reason to hold.

## Steps

1. **Locate the meta repo** and refuse if not in it.

2. **Dedup against prior proposals.** Read `docs/system-proposals/` (and
   its `_index.md` if present). Do not re-propose an idea already pending or
   already decided (accepted/rejected) there — a `status:` field records the
   disposition. If new evidence materially strengthens a previously-rejected
   idea, a *fresh* proposal that cites the rejection and the new evidence is
   allowed; a verbatim re-proposal is not.

3. **Survey the graph.** Read `concepts/` (favor `status:` growing/mature/
   active and concepts with strong `sources:`), the MoCs, and the most
   recent high-`credibility` literature notes. Build a short list of ideas
   that plausibly bear on how *this box's* skills/hooks/rules work.

4. **Test each candidate against both gates.** Ground it by reading the
   actual target file in `~/claude-system`. Discard anything that fails
   either gate; note the strongest one or two discards in the run log so the
   reasoning is visible.

5. **Write a proposal per survivor** at
   `docs/system-proposals/YYYY-MM-DD-<slug>.md` with flat frontmatter:

   ```yaml
   ---
   kind: system-proposal
   slug: <slug>
   added: "<today>"
   target: "<path under ~/claude-system, e.g. claude/skills/digest/SKILL.md>"
   change_type: edit | new-file | removal | consolidation
   adds_surface_area: true | false
   evidence_citekeys: [<citekey>, ...]
   evidence_strength: "<peer-reviewed | code-released | N-attestations>; credibility ~<n>"
   status: proposed            # proposed | accepted | rejected | superseded
   recommendation: adopt | adopt-with-changes | hold
   ---
   ```

   Body sections (keep them tight):
   - **The change** — concretely, what file changes and how. Quote the
     current text and show the proposed text for an edit.
   - **Why (logical case)** — the reasoning from system behavior to the
     change. What problem it fixes or what it improves.
   - **Why (reputable evidence)** — the citekeys, why they pass Gate 1, and
     what each actually demonstrates. No hand-waving to "the literature."
   - **Simplicity assessment** — Gate 2: does it add/remove surface area,
     was a simpler form considered, why this form.
   - **Risks & what could make this wrong** — be adversarial about your own
     proposal.
   - **Recommendation** — adopt / adopt-with-changes / hold, one paragraph.

6. **Index + log.** Append a one-line pointer to
   `docs/system-proposals/_index.md` (create it if absent). Append to
   `_meta/log.md`: `YYYY-MM-DD HH:MM elevate proposals=<k> considered=<m>`.
   On a zero-proposal cycle, still write the log line with `proposals=0` and
   a few words on what was considered and held — silence must not read as
   "nothing was examined."

7. **Persist** per `~/claude-system/claude/rules/agency.md`: commit and push the
   proposal files **in the agentic-research repo only**. Do **not** stage,
   commit, or push anything in `~/claude-system`.

## Constraints

- **Never write to `~/claude-system`** — not the skill files, not settings,
  not a "draft" branch. Read-only there. Violating this defeats the
  human-review gate.
- One idea per proposal file. A bundle of unrelated changes is not
  reviewable.
- No proposal may depend on `test/` access or weaken the HCE discipline
  (`evaluation.md`); a proposal that touches evaluation rules must
  strengthen, not loosen, the holdout.
- Prefer amending an existing skill/rule over adding a new one. The bias is
  toward a smaller system, not a larger one.

## Why this exists

The user's directive: periodically evaluate whether ideas curated here
should be adopted into the Claude research system, with a good logical and
reputable reason required, every good case elevated for human review, and
simplicity high among the judging priorities. This skill encodes exactly
that policy and nothing more. It is invoked weekly by cron
(`~/.claude/schedule/agentic-research-elevate.sh`) and can be run by hand
any time with `/elevate`.
