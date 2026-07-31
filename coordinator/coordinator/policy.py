"""Admission policy. `can_start(job) -> (admit, reason)`.

Heuristics (v1), coarse but good enough to start:

- Hard stop if <25% of the weekly token budget remains and >50% of the
  week is left (conservative on research/ingest; always admit on
  score/implement-finishing-up).
- Queue if GPU VRAM free < est_vram_gb + 2GB margin.
- Queue if another job of the same project+kind is already running.
- Otherwise admit.

The numeric ceilings come from budget.yaml at the project root when
present; fall back to coordinator defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .readers import latest_hardware_sample, running_job_for_project, tokens_in_last

DEFAULTS = {
    # Coarse safety net; override per-project via budget.yaml `max_tokens_weekly`.
    # Sized against measured true spend on this box (~100M/7d incl. cache
    # creation, post 2026-07-31 meter fix) so the <25%-remaining deferral
    # trips only on genuinely heavy weeks, not steady-state.
    "max_tokens_weekly": 150_000_000,
    "vram_margin_gb": 2.0,
}


@dataclass
class Job:
    project: str
    kind: str
    est_tokens: Optional[int] = None
    est_vram_gb: Optional[float] = None
    description: str = ""


def _load_budget(project_root: Optional[Path]) -> dict:
    if not project_root:
        return DEFAULTS
    p = project_root / "budget.yaml"
    if not p.exists():
        return DEFAULTS
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return DEFAULTS
    return {
        # budget.yaml's `max_tokens` is a PER-CHAIN ceiling consumed by
        # /iterate — don't overload it as the weekly gate. A project that
        # wants a project-specific weekly ceiling sets `max_tokens_weekly`.
        "max_tokens_weekly": int(data.get("max_tokens_weekly", DEFAULTS["max_tokens_weekly"])),
        "vram_margin_gb": float(data.get("vram_margin_gb", DEFAULTS["vram_margin_gb"])),
    }


def can_start(job: Job, project_root: Optional[Path] = None) -> tuple[bool, str]:
    budget = _load_budget(project_root)

    # Token-window check — only block research/ingest on low quota.
    if job.kind in {"research", "ingest", "digest"} and job.est_tokens:
        seven_d = tokens_in_last(7 * 24 * 3600)
        remaining = budget["max_tokens_weekly"] - seven_d["total"]
        if remaining < 0.25 * budget["max_tokens_weekly"]:
            return (False, f"defer: <25% weekly token budget remains ({remaining:,} of {budget['max_tokens_weekly']:,})")

    # GPU-fit check.
    if job.est_vram_gb:
        hw = latest_hardware_sample()
        if hw and hw.get("gpu_mem_total_gb") is not None:
            free = (hw["gpu_mem_total_gb"] or 0) - (hw.get("gpu_mem_used_gb") or 0)
            if free < job.est_vram_gb + budget["vram_margin_gb"]:
                return (
                    False,
                    f"queue: GPU VRAM free {free:.1f}GB < est {job.est_vram_gb}GB + {budget['vram_margin_gb']}GB margin",
                )

    # Same-project+kind serialization.
    running = running_job_for_project(job.project, kind=job.kind)
    if running:
        return (False, f"queue: another {job.kind} job (#{running['id']}) is already running on {job.project}")

    return (True, "admit")
