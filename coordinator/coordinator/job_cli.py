"""CLI helpers invoked by /implement, /iterate, /ingest, /digest.

Subcommands:
    declare <project> <kind> [--est-tokens N] [--est-vram-gb F] [--description "..."]
        → inserts a queued job, prints the job id.

    start <id>
        → marks job running.

    complete <id> [--actual-tokens N] [--actual-gpu-minutes F] [--status done|failed] [--note "..."]
        → closes the job.
"""
from __future__ import annotations

import argparse
import sys

from .writers import complete_job, declare_job, start_job


def main() -> int:
    p = argparse.ArgumentParser(prog="claude-coordinator-job")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("declare")
    d.add_argument("project")
    d.add_argument("kind")
    d.add_argument("--est-tokens", type=int, default=None)
    d.add_argument("--est-gpu-minutes", type=float, default=None)
    d.add_argument("--est-vram-gb", type=float, default=None)
    d.add_argument("--priority", type=int, default=0)
    d.add_argument("--description", default="")
    d.add_argument("--note", default="")

    s = sub.add_parser("start")
    s.add_argument("id", type=int)

    c = sub.add_parser("complete")
    c.add_argument("id", type=int)
    c.add_argument("--actual-tokens", type=int, default=None)
    c.add_argument("--actual-gpu-minutes", type=float, default=None)
    c.add_argument("--status", default="done", choices=["done", "failed", "deferred"])
    c.add_argument("--note", default="")

    args = p.parse_args()

    if args.cmd == "declare":
        job_id = declare_job(
            project=args.project,
            kind=args.kind,
            description=args.description,
            est_tokens=args.est_tokens,
            est_gpu_minutes=args.est_gpu_minutes,
            est_vram_gb=args.est_vram_gb,
            priority=args.priority,
            note=args.note,
        )
        print(job_id)
    elif args.cmd == "start":
        start_job(args.id)
    elif args.cmd == "complete":
        complete_job(
            args.id,
            actual_tokens=args.actual_tokens,
            actual_gpu_minutes=args.actual_gpu_minutes,
            status=args.status,
            note=args.note,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
