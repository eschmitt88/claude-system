---
name: mle-task
description: Scaffold an MLE-bench task into the active project. Resolves the task's prepared data from the local MLE-bench cache, creates a dated experiment folder with train/ and test/ symlinks, writes splits.yaml (stratified / temporal / random strategy matched to the task), drafts a seed proposal under experiments/_proposals/, and writes an experiment-level CLAUDE.md with task-specific context. Does not run /implement or /iterate — hands off to the user.
respects:
  - ~/claude-system/claude/rules/evaluation.md
---

# mle-task

Scaffold one MLE-bench task in the active project so that `/implement`
and `/iterate` can drive it through the normal research loop.

## Arguments

- `<task-id>` — required. A valid MLE-bench competition ID (e.g.
  `random-acts-of-pizza`, `nomad2018-predict-transparent-conductors`).
  Refuse if the ID isn't present in
  `external/mle-bench/mlebench/competitions/`.

## Evaluation discipline (HCE)

`/mle-task` is a **search-phase** skill. It reads the task's README,
`config.yaml`, and training data to shape the seed proposal and the
experiment CLAUDE.md. It **never reads from** `prepared/private/`
(the grader's labels) and **never reads from** or previews
`<experiment>/test/`. Only `/mle-score` touches `test/`. See
`~/claude-system/claude/rules/evaluation.md`.

## Steps

1. **Refuse if the cwd is not inside a project.**

2. **Locate the MLE-bench install**:
   - Expect `<project>/external/mle-bench/` with a working `.venv/`.
   - Refuse with a one-line instruction if missing: "Clone MLE-bench
     to `external/mle-bench/` and `uv pip install -e .` inside its
     `.venv/` before running `/mle-task`."

3. **Validate the task ID**:
   - Path `external/mle-bench/mlebench/competitions/<task-id>/` must
     exist with `config.yaml`, `description.md`, `grade.py`.
   - Refuse if not.

4. **Confirm data is materialized**:
   - Expect `<project>/data/mle/<task-id>/prepared/public/` to exist.
   - If missing, tell the user to run (and do not attempt on their
     behalf):
     ```
     source external/mle-bench/.venv/bin/activate
     mlebench prepare -c <task-id> --data-dir data/mle
     ```

5. **Read task metadata** from `external/mle-bench/mlebench/competitions/<task-id>/config.yaml`:
   - `grader.name` → the metric (e.g. `auc-roc`, `accuracy`, `rmse`).
   - `competition_type` → `simple` | other.
   - `description` path → read it for the experiment CLAUDE.md.

6. **Inspect the public data layout** (to drive `train/`, `test/`
   symlinks and `splits.yaml`):
   - List files under `data/mle/<task-id>/prepared/public/`.
   - Identify the training file (largest file with labels; often
     `train.csv`, `train.json`, or a directory).
   - Identify the test-features file (test.csv / test.json — the
     unlabeled input the grader expects predictions for).
   - Identify `sampleSubmission.csv` if present — this documents the
     submission format.
   - **Do not** open `data/mle/<task-id>/prepared/private/` — that's
     the grader's ground truth.

7. **Compute the experiment folder name**:
   `experiments/YYYY-MM-DD-mle-<task-id>/` using today's local date.
   Refuse if it already exists (same-day re-runs must be resolved
   manually — tell the user to `rm -rf` or rename the prior folder).

8. **Create the experiment scaffold**:

   ```
   <experiment>/
     README.md          # from _meta/templates/experiment.md
     config.yaml        # seed: 42
     notes.qmd          # Quarto stub
     results/.gitkeep
     log.md             # header only
     metrics.json       # {}
     splits.yaml        # see step 9
     CLAUDE.md          # task-specific context (see step 11)
     train/             # symlink — see step 10
     test/              # symlink — see step 10
   ```

   Seed `README.md`'s frontmatter from the task:

   ```yaml
   ---
   kind: experiment
   slug: mle-<task-id>
   date: <YYYY-MM-DD>
   status: running
   hypothesis: "Baseline <model-family> on <task-id> (<metric-name>)."
   result: ""
   related_concepts: [hce-evaluation, pass-at-k]
   related_literature: []
   tags: [mle-bench, <task-id>]
   ---
   ```

   `<model-family>` is a reasonable default given the task type
   (e.g. "logistic regression" for binary tabular, "gradient boosting"
   for tabular regression, "transformer encoder" for text
   classification). The seed proposal in step 12 restates this.

9. **Write `<experiment>/splits.yaml`** with a val split carved from
   train, seeded. Strategy matches the task:

   | Task signal | Strategy | val_fraction |
   |---|---|---|
   | classification (grader name in `auc-roc`, `accuracy`, `f1`, `log-loss`) | stratified | 0.2 |
   | regression with temporal column (`date`, `timestamp`, `time`) | temporal (hold out the latest 20%) | 0.2 |
   | regression / other | random 80/20 | 0.2 |
   | tiny train sets (<1000 rows) | stratified or random, val_fraction 0.15 | 0.15 |

   Emit the strategy choice and rationale as a comment at the top of
   `splits.yaml`. Example for `random-acts-of-pizza`:

   ```yaml
   # Strategy: stratified (grader is auc-roc; binary classification)
   # Rationale: keep positive-class prevalence consistent across
   # train/val. Val is for the search loop only; MLE-bench's held-out
   # test set lives under `prepared/private/` and is only touched by
   # /mle-score.
   seed: 42
   strategy: stratified
   val_fraction: 0.2
   target_column: requester_received_pizza
   id_column: request_id
   ```

10. **Create the symlinks**:

    ```
    <experiment>/train -> <project>/data/mle/<task-id>/prepared/public/
    <experiment>/test  -> <project>/data/mle/<task-id>/prepared/public/
    ```

    Note that both the training files and the test-features file live
    under `prepared/public/` in MLE-bench's layout. Agents must be
    disciplined to read only training files from `train/` during
    search, and only read test features from `test/` during the
    `/mle-score` inference pass. The symlink targets can overlap
    without corrupting the HCE rule as long as code honors the
    `train/` vs `test/` directory boundary.

    If the task's layout is pathological (e.g. a single giant archive
    with both train and test inside), flag it and ask the user
    before creating the symlinks.

11. **Write `<experiment>/CLAUDE.md`** — task-specific context only.
    **Do not** re-import the four standard concepts
    (`hce-evaluation`, `citation-anchoring`, `pass-at-k`,
    `budget-as-ceiling`) — those are inherited from the project root.
    Include:

    - One-paragraph task summary (pulled from the task's
      `description.md` intro).
    - Data shape: row counts for train and test-features, column
      names and types (for tabular) or representative example (for
      text/image).
    - Metric: grader name and submission-format description, pulled
      from `config.yaml` and `sampleSubmission.csv`.
    - Submission format: exact column names and example row.
    - Any task-specific `@import`s beyond the standard four (rare at
      smoke-test stage — usually none).

12. **Write the seed proposal** at
    `experiments/_proposals/YYYY-MM-DD-mle-<task-id>.md` with flat
    YAML frontmatter matching `/propose`'s format:

    ```yaml
    ---
    slug: mle-<task-id>
    date: <YYYY-MM-DD>
    status: proposed
    hypothesis: "<one sentence: a <baseline-family> baseline on <task-id> reaches <ballpark-metric-value> on the val split.>"
    rationale: "<why this baseline is the right first step — usually: cheap, canonical for this task type, gives a reference number for later iterations.>"
    reads:
      - external/mle-bench/mlebench/competitions/<task-id>/description.md
      - experiments/YYYY-MM-DD-mle-<task-id>/train/
    expected_metric:
      name: <grader.name from task config>
      value: <ballpark — a plausible baseline number, not SOTA>
      on: val
    design_sketch: "<3-5 bullets: features, model, training, evaluation.>"
    risks:
      - "<one or two likely failure modes>"
    related_prior: []
    estimated_runtime: "<minutes — smoke test shouldn't exceed 30min/cycle>"
    ---

    # mle-<task-id> baseline

    <Prose argument — one or two paragraphs explaining the baseline choice.
    Reference the task's metric and data size. If related to prior work on
    this task type, cite the relevant concept or literature note.>
    ```

    `reads:` must not include anything under `test/` or
    `prepared/private/`.

13. **Update `_meta/index.md`**: add the new folder to "Active
    experiments".

14. **Append to `_meta/log.md`**:
    `YYYY-MM-DD HH:MM mle-task <task-id>`.

15. **Show the diff and wait for confirmation before writing.**
    After the user approves, print the experiment folder's absolute
    path and a closing message:

    > Scaffold complete at `<experiment>/`.
    > Seed proposal: `<proposal-path>`.
    >
    > Next:
    > 1. `/implement <proposal-path>` — run the baseline as cycle 0.
    > 2. `/iterate --chain <N> --chain-until "<condition>"` — drive
    >    further cycles.
    >
    > `/mle-score <experiment-path>` is the **only** skill that
    > touches `test/` for final grading — invoke it after the chain
    > halts, against the experiment with the best `metrics.json`.

## Notes

- This skill does not invoke `/implement` or `/iterate`. A fresh
  proposal exists; the user chooses when to spend tokens on it.
- Same-day re-runs of the same task need to be resolved manually by
  removing the prior folder — the date-slug convention collides
  otherwise. This is rare and intentional: smoke tests are one-shot.
- If the task's grader requires Docker (check its `config.yaml`),
  mention it in the experiment CLAUDE.md so `/mle-score` knows.
- The task's `kernels.txt` often lists Kaggle notebooks that
  top-solved the competition. Treat these as reference, not target:
  the smoke test is about proving the pipeline runs, not matching
  Kaggle's leaderboard.
