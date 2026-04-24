---
name: expand
description: /expand <proposal-path> [--n N] takes one proposal and produces N alternative implementations that share the hypothesis but differ in approach — architectures, training regimes, feature engineering, evaluation strategies. Each child lands in experiments/_proposals/_expansions/<parent-slug>/<child-slug>.md with a parent: frontmatter field. Default N=3.
respects:
  - ~/.claude/rules/evaluation.md
---

# expand

Breadth-first ideation on a single hypothesis. Given a proposal, emit
N sibling proposals that test the same claim via substantively
different approaches.

This is the seed for MCTS-over-proposals. For now expansions are
leaves — each child is an ordinary proposal that can be `/implement`-ed
directly or picked up by `/iterate`. Later revisions may add
scoring, pruning, or rollout logic.

## Arguments

- `<proposal-path>` — path to an existing file under
  `experiments/_proposals/` (not `_done/`, not `_failed/`). Required.
  The parent must have frontmatter `status: proposed`.
- `--n <N>` — optional. Number of children to produce. Default **3**.

## Steps

1. **Locate the active project** and read the parent proposal in full
   (frontmatter + body). Read any files it wikilinks in `reads:`
   (one hop) so children can ground themselves in the same evidence.

2. **Decide what to vary.** The model picks the axes — do not
   enforce a fixed operator set. Useful dimensions include:

   - **Architecture** — different model family / inductive bias.
   - **Training regime** — different optimizer, schedule, regularization,
     curriculum, loss.
   - **Feature engineering / inputs** — different representation of
     the same data.
   - **Evaluation strategy** — different metric, different validation
     split slicing, different calibration.
   - **Data scale** — same approach on more or less data.
   - **Prior integration** — different way of folding in an existing
     technique from `literature/`.

   A good expansion set is **genuinely diverse** — two children whose
   only difference is a hyperparameter are wasted slots. If you can
   only come up with fewer than N diverse variants, emit what you
   have and say so rather than padding.

3. **For each child**, produce a proposal file identical in structure
   to what `/propose` emits (same flat frontmatter keys, same prose
   body). The hypothesis stays close to the parent's; everything else
   is the child's own. Add two frontmatter fields the base template
   doesn't have:

   ```yaml
   parent: "<parent-slug>"
   expansion_axis: "<one-line label for what varies>"
   ```

   Children must keep `status: proposed` and a fresh `date:` of today.

4. **Path**: `experiments/_proposals/_expansions/<parent-slug>/<child-slug>.md`.
   Create the directory on first use. Child slugs should be short and
   reflect the axis — e.g. parent `noisy-pair-downweighting` might
   spawn `noisy-pair-downweighting-ema`, `-loss-mask`, `-contrastive`.

5. **Do not modify the parent.** The parent stays in
   `experiments/_proposals/` with `status: proposed`. It remains
   individually `/implement`-able; the user may also choose to
   implement a child in its place.

6. **Show the diffs** — one per child — and wait for confirmation
   before writing.

7. **Append to `_meta/log.md`** once, after writing:
   `YYYY-MM-DD HH:MM expand <parent-slug> → <n> children`.

## Constraints

- Does not spawn a subagent. `/expand` is ideation; compute happens
  only under `/implement`.
- Does not touch `dvc.yaml`, `config.yaml`, or experiment folders.
- Every child's `reads:` list must still be real files the skill
  actually opened (same rule as `/propose`). Decorative citations
  are not permitted.
- Children inherit the parent's evaluation discipline:
  `~/.claude/rules/evaluation.md` — validation metrics only, no
  `test/` peeking.

## Notes

- Treat `--n` as a cap, not a target. N=3 diverse children beat N=5
  with two near-duplicates.
- `/lint` flags any child older than 7 days with no `/implement` run
  — unimplemented expansions are either pruning candidates or
  forgotten leaves.
