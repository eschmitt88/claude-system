"""CLI for /plan. Given a proposed job, consult policy.can_start() and
print an admit/defer verdict with reasoning.

Usage:
    claude-coordinator-plan <project> <kind> [--est-tokens N] [--est-vram-gb F] [--description "..."]

Output is human-readable; pass --json for structured.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .policy import Job, can_start


def _find_project_root(project: str) -> Path | None:
    # Try ~/projects/research/<project>/ as a convention.
    root = Path.home() / "projects" / "research" / project
    if root.exists():
        return root
    return None


def main() -> int:
    p = argparse.ArgumentParser(prog="claude-coordinator-plan")
    p.add_argument("project")
    p.add_argument("kind", choices=["research", "implement", "iterate", "ingest", "digest", "score"])
    p.add_argument("--est-tokens", type=int, default=None)
    p.add_argument("--est-vram-gb", type=float, default=None)
    p.add_argument("--description", default="")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    job = Job(
        project=args.project,
        kind=args.kind,
        est_tokens=args.est_tokens,
        est_vram_gb=args.est_vram_gb,
        description=args.description,
    )
    root = _find_project_root(args.project)
    admit, reason = can_start(job, project_root=root)

    if args.json:
        print(json.dumps({"admit": admit, "reason": reason, "project_root": str(root) if root else None}))
    else:
        verdict = "ADMIT" if admit else "DEFER"
        print(f"{verdict}: {reason}")
        if root:
            print(f"  (project root: {root})")
    # Exit non-zero on defer so shell callers can branch.
    return 0 if admit else 2


if __name__ == "__main__":
    raise SystemExit(main())
