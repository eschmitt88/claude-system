---
name: plan
description: Before starting a non-trivial job, estimate its resource cost, consult the coordinator's admission policy, and get an admit/defer verdict with reason. Wraps ~/claude-system/coordinator/.venv/bin/claude-coordinator-plan.
---

# plan

Ask the coordinator whether a proposed job should start now or wait.

## When to use

Call `/plan` before `/implement`, `/iterate`, `/ingest`, `/digest`, or
any loop that spends >200k tokens or touches GPU. For cheap local
operations (file edits, small reads, `/wrap`, `/status`) skip it —
`/plan` is overhead for small jobs.

## Arguments

- `<description>` — free-text one-liner describing the job.

Before calling, estimate:

- **kind** — one of `research`, `implement`, `iterate`, `ingest`,
  `digest`, `score`.
- **est_tokens** — integer token budget. Use history as a guide:
  `/implement` cycles on small tasks run 40–60k; `/iterate --chain N`
  runs ~400–500k per cycle; `/ingest` on a paper runs 20–40k.
- **est_vram_gb** — only if the job actually loads a model to GPU.
  Leave unset for CPU-only work.

## Steps

1. **Find the active project** (nearest ancestor with `CLAUDE.md` and
   `_meta/`). Refuse outside one.

2. **Estimate**. Think out loud for one paragraph: what kind of work,
   roughly how many tokens / how much VRAM, why. Err on the high side
   — the coordinator rejects on `est_tokens > quota_remaining`, so
   under-estimating hides a real problem.

3. **Shell out to the CLI**:

   ```bash
   ~/claude-system/coordinator/.venv/bin/claude-coordinator-plan \
     <project-slug> <kind> \
     --est-tokens <N> [--est-vram-gb F] \
     --description "<one-liner>"
   ```

   Exit code 0 = admit, 2 = defer.

4. **Report** the verdict and reason to the user verbatim. If admit:
   offer to declare the job and proceed. If defer: state the reason,
   suggest the next check time (e.g. "after the 5h window reset" or
   "when GPU frees up"), and stop.

5. **On admit, declare the job** (optional but recommended — it shows
   up in `/status` as running):

   ```bash
   JOB_ID=$(~/claude-system/coordinator/.venv/bin/claude-coordinator-job \
     declare <project-slug> <kind> --est-tokens <N> --description "...")
   ~/claude-system/coordinator/.venv/bin/claude-coordinator-job start $JOB_ID
   ```

   When the job completes, close it:

   ```bash
   ~/claude-system/coordinator/.venv/bin/claude-coordinator-job \
     complete $JOB_ID --actual-tokens <measured> [--status done|failed]
   ```

## Policy recap (for context)

- Deferred when <25% of the weekly token budget remains and the job
  is `research` / `ingest` / `digest` (deprioritized in tight quota).
- Queued when GPU VRAM free < est_vram_gb + 2GB margin.
- Queued when another job of the same `(project, kind)` is running.
- Admitted otherwise.

Override logic lives in `~/claude-system/coordinator/coordinator/policy.py`
if the defaults need tuning.
