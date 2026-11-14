---
name: elevate
description: Hub only. Tests ideas in the agentic-research knowledge graph against an evidence gate and a simplicity gate, and writes proposals for changes to claude-system under docs/system-proposals/ for human review. Never edits claude-system. Most cycles produce none.
respects:
  - ~/claude-system/claude/rules/agency.md
---

# elevate

**First, Read every file listed under `respects:` in the frontmatter.** Framework rules load no other way.

The hub curates findings about how research agents are built. Some bear on
the system this box runs: the skills, hooks and rules in `~/claude-system`.
This skill reads the graph, compares it with the live system, and writes
**proposals for a human to review**.

It never edits `~/claude-system`, not even a draft branch. A human accepts
or rejects, and an accepted change is made by the human or by a session
they authorize. That separation is the point.

Run only inside the `agentic-research` repo. Proposal targets are files
under `~/claude-system/claude/` (skills, rules, hooks, settings,
`CLAUDE.md`); read the target before proposing a change to it.

## The two gates

An idea becomes a proposal only if it clears both. When in doubt, don't
propose. A cycle with zero proposals is the normal outcome.

**Gate 1, reputable evidence.** At least one of: a peer-reviewed source
(`peer_reviewed: true`); a source with released code or artifacts
(`code_url` set); three or more independent attestations across distinct
groups. And the supporting notes' `credibility:` is ≥3 on balance. Cite
the citekeys. An idea resting on credibility ≤2 preprints is recorded as
considered-and-held.

**Gate 2, simplicity.** Judge the change by its effect on the system's
total surface area.

- Removing, consolidating or clarifying can pass on a modest evidence base,
  because the downside is low.
- Adding a skill, hook, rule or knob must say what complexity it adds, why
  a smaller form will not do, and why the benefit is worth maintaining
  forever. Default to rejecting net-new complexity.
- **Text has a budget too.** A proposal that adds words to a skill, a rule
  or `CLAUDE.md` names what it removes or shortens in the same file, and
  states the net word change. Paragraphs added one accepted proposal at a
  time are how the instruction corpus grew back to its pre-ablation size.
- Propose the simplest viable form. If the only viable form is complex,
  that is a reason to hold.

## Steps

1. **Dedup.** Read `docs/system-proposals/` and its `_index.md`. Don't
   re-propose an idea that is pending or decided (`status:`). New evidence
   that materially strengthens a rejected idea may justify a fresh
   proposal that cites the rejection.

2. **Survey.** Read `concepts/` (favouring growing, mature or active ones
   with strong `sources:`), the MoCs, and the recent high-credibility
   literature notes. Shortlist ideas that bear on how this box's skills,
   hooks and rules work.

3. **Test each candidate against both gates**, reading the actual target
   file. Note the strongest one or two discards in the run log.

4. **Run the paired control.** Pick one `status: accepted` proposal,
   rotating oldest-first, and re-test it against the gates as they read
   today, using only the evidence it cited at the time. It should pass. If
   it would now be rejected, the gates have drifted strict: say so in the
   log and name the gate. A cycle where the control fails is a broken gate,
   and from the output alone it looks identical to a quiet one. (This
   catches drift toward strictness, not a gate mis-set from the start.)

5. **Write one proposal per survivor** at
   `docs/system-proposals/YYYY-MM-DD-<slug>.md`:

   ```yaml
   ---
   kind: system-proposal
   slug: <slug>
   added: "<today>"
   target: "<path under ~/claude-system>"
   change_type: edit | new-file | removal | consolidation
   adds_surface_area: true | false
   evidence_citekeys: [<citekey>, ...]
   evidence_strength: "<peer-reviewed | code-released | N-attestations>; credibility ~<n>"
   status: proposed            # proposed | accepted | rejected | superseded
   recommendation: adopt | adopt-with-changes | hold
   ---
   ```

   Body, kept tight: **The change** (quote the current text and show the
   proposed text); **Why (logical case)**; **Why (reputable evidence)**
   (what each citekey actually demonstrates); **Simplicity assessment**
   (including the net word change); **Risks & what could make this wrong**
   (be adversarial); **Recommendation**.

6. **Index and log.** Add a row to `_index.md`. Append to `_meta/log.md`:
   `YYYY-MM-DD elevate proposals=<k> considered=<m> control=<slug>:<pass|fail>`,
   with a few words on what was considered and held. Silence must not read
   as "nothing was examined".

7. **Commit and push in this repo only**, by path. Never stage anything in
   `~/claude-system`.

## Constraints

- One idea per proposal. A bundle is not reviewable.
- A proposal touching `evaluation.md` must strengthen the holdout, never
  loosen it.
- Prefer amending an existing file over adding a new one.

Invoked weekly by cron, or by hand.
