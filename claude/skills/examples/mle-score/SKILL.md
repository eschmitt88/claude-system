---
name: mle-score
description: Run final-scoring pass on an MLE-bench experiment. Inferences the trained model on the held-out test/ directory (the only skill allowed to read test/), produces submission.csv in MLE-bench format, invokes `mlebench grade-sample`, and writes final_metrics.json with grader output + provenance (task ID, grader version, timestamp, MLE-bench git SHA). Does not mutate metrics.json. Appends one FINAL_SCORE line to _meta/iteration_log.md for /lint to grep.
respects:
  - ~/.claude/rules/evaluation.md
---

# mle-score

The **final-scoring pass** for an MLE-bench experiment. Read the HCE
rule (`~/.claude/rules/evaluation.md`) before touching this skill.

## Arguments

- `<experiment-path>` — required. Path to a completed experiment
  folder (either relative to the project root, or absolute). Refuse
  if:
  - the path doesn't exist,
  - it doesn't contain `metrics.json` (experiment hasn't completed
    search — don't grade an unfinished run),
  - it doesn't contain `test/` (not an MLE-bench experiment),
  - it already contains `final_metrics.json` (already graded —
    require an explicit delete before regrading).

## Evaluation discipline (HCE)

**This is the one skill in the stack allowed to read from `test/`.**
Everything inside `/iterate` (including `--ensemble`), `/implement`,
`/propose` (including `--expand`), and `/mle-task` treats `test/` as off-limits. `/mle-score`
runs exactly once per experiment — the final-scoring pass — and
writes `final_metrics.json`. The search-signal file (`metrics.json`)
is not touched.

If the experiment is missing `metrics.json`, refuse. Graders exist to
score completed work, not to rescue aborted runs.

## Steps

1. **Refuse if the cwd is not inside a project.**

2. **Validate the experiment**:
   - Resolve `<experiment-path>` to an absolute path.
   - Confirm `<experiment>/metrics.json` exists and is non-empty
     (contains real numbers, not `{}`).
   - Confirm `<experiment>/test/` exists (directory or symlink).
   - Confirm `<experiment>/final_metrics.json` does **not** exist.
   - Read `<experiment>/README.md` frontmatter and `config.yaml` to
     identify the task ID (look for `tags: [mle-bench, <task-id>]`
     or a `task_id` field in config). If ambiguous, stop and ask
     the user.

3. **Locate MLE-bench**:
   - Expect `<project>/external/mle-bench/` with a `.venv/` and a
     working `mlebench` binary.
   - Read the task's grader config at
     `external/mle-bench/mlebench/competitions/<task-id>/config.yaml`.
   - If the config specifies a Docker-based grader, note this and
     branch in step 5 accordingly.

4. **Run inference to produce `submission.csv`**:
   - Load the trained model and inference entry point from the
     experiment. Conventions (in order of preference):
     1. `<experiment>/predict.py` with a `main(test_dir, out_csv)`
        function — run it with `test/` as input and write
        `<experiment>/submission.csv`.
     2. A `predict` entry point in the experiment's `config.yaml`
        under a `scripts:` section.
     3. If neither exists, stop and ask the user — don't guess.
   - Invoke the inference script with the experiment's venv (or the
     project venv if the experiment didn't create its own). Pass
     `<experiment>/test/` as the input directory and
     `<experiment>/submission.csv` as the output path.
   - Validate the submission against the task's expected format by
     comparing column names + row count to `sampleSubmission.csv`
     (found under `data/mle/<task-id>/prepared/public/` or the
     task's `kernels.txt` reference). Refuse to proceed on format
     mismatch — fix the inference script first.

5. **Grade the submission**:
   - Activate the MLE-bench venv:
     `source external/mle-bench/.venv/bin/activate`.
   - Default (non-Docker) path:
     ```
     mlebench grade-sample <experiment>/submission.csv <task-id>
     ```
     Capture stdout/stderr and exit status.
   - Docker path (if the task's config requires it):
     ```
     docker run --rm \
       -v <experiment>/submission.csv:/tmp/submission.csv:ro \
       -v <project>/data/mle/<task-id>/prepared/private:/grader/private:ro \
       <task-specified-image> \
       mlebench grade-sample /tmp/submission.csv <task-id>
     ```
     The exact mount paths are task-dependent — if the task's
     `config.yaml` specifies a grader image, consult its
     documentation. If unclear, stop and ask.
   - Parse the grader's output into a numeric score. MLE-bench's
     `grade-sample` emits JSON-like structured output; extract the
     primary metric value and pass/fail flag.

6. **Write `final_metrics.json`**:

   ```json
   {
     "task_id": "<task-id>",
     "metric_name": "<grader.name from task config>",
     "metric_value": <numeric score>,
     "any_medal": <bool, if applicable — None for simple tasks>,
     "gold_threshold": <number, if MLE-bench reports it>,
     "silver_threshold": <number>,
     "bronze_threshold": <number>,
     "submission_rows": <row count>,
     "graded_at": "<ISO timestamp>",
     "mle_bench_sha": "<git rev-parse HEAD inside external/mle-bench>",
     "grader_command": "<exact command line used>"
   }
   ```

   Do **not** mutate `metrics.json`. The two files are different by
   design: one is the search signal, one is the held-out result.

7. **Append one line to `_meta/iteration_log.md`**:

   ```
   FINAL_SCORE: <task-id> metric=<metric-value> experiment=<slug>
   ```

   Use the exact prefix `FINAL_SCORE:` (no other prefix in this log
   starts with those characters). `/lint` greps for this line when
   auditing HCE rule compliance. Create the log file if missing.

8. **Update the experiment's `README.md`**:
   - Set `status:` to `done`.
   - Fill in the `result:` frontmatter field with a one-sentence
     summary that references `final_metrics.json` explicitly
     (not `metrics.json`): e.g. "AUC-ROC 0.72 on held-out test
     (see final_metrics.json)."

9. **Print a one-screen summary** to the user:
   - Task ID, metric name, val-split value (from `metrics.json`),
     test-split value (from `final_metrics.json`), and the delta.
   - A note if the delta is larger than what val-split sampling
     noise can explain for that val size (rough rule: 5-point swings
     on val sets <500 are routine; on val sets >5000 they are not).

## Notes

- **Only this skill reads `test/`.** If you find yourself reading
  from `test/` or `prepared/private/` inside another skill, stop —
  that's an HCE rule violation.
- The MLE-bench grader is deterministic, but the search loop that
  produced the submission generally is not. Mean±std reporting
  belongs in the experiment's `metrics.json` (from `--seeds N` runs
  via `/implement`); `final_metrics.json` is one-shot per
  experiment.
- Regrading: to rerun the grader (e.g. after fixing `predict.py`),
  `rm <experiment>/final_metrics.json` and re-invoke `/mle-score`.
  Do not overwrite silently.
- The `_meta/iteration_log.md` line is append-only. If you need to
  correct a value, append a new line with an ISO timestamp in the
  slug — never edit the old line.
