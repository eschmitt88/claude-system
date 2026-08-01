#!/usr/bin/env python3
"""chain_budget.py — evaluate /iterate chain halting conditions.

Deterministic port of the halting arithmetic that used to live as prose
in iterate/SKILL.md (instruction-ablation-program, phase 3). The skill
supplies its chain-local counters; this script reads budget.yaml and
the token log, evaluates every condition, and reports what tripped.

Usage:
    python chain_budget.py --root DIR --chain-start 2026-08-01T10:00:00Z \
        [--until wall_hours:gte:8] [--until metric:gte:0.92] \
        [--experiments-completed 3] [--consecutive-no-improvement 1] \
        [--metric-value 0.87]

Condition grammar: <key>:<op>:<value>
  key ∈ {metric, wall_hours, tokens_spent, consecutive_no_improvement,
         experiments_completed}
  op  ∈ {gte, lte, eq}
Conditions OR together; budget.yaml ceilings are implicit conditions.

Needs PyYAML — run via the coordinator venv.
Prints JSON: {"halt": bool, "tripped": [...], "totals": {...}}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import yaml

OPS = {"gte": lambda a, b: a >= b, "lte": lambda a, b: a <= b,
       "eq": lambda a, b: a == b}
BUDGET_IMPLICIT = {
    "max_wall_hours": ("wall_hours", "gte"),
    "max_tokens": ("tokens_spent", "gte"),
    "max_experiments": ("experiments_completed", "gte"),
    "max_consecutive_no_improvement": ("consecutive_no_improvement", "gte"),
}


def tokens_since(root: Path, start: dt.datetime) -> int:
    total = 0
    tl = root / "_meta" / "token_log.ndjson"
    if not tl.is_file():
        return 0
    for ln in tl.read_text(errors="replace").splitlines():
        try:
            row = json.loads(ln)
            ts = dt.datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if ts >= start:
            total += sum(int(row.get(k, 0) or 0) for k in
                         ("input_tokens", "output_tokens", "cache_creation_tokens"))
    return total


def disk_gb(root: Path) -> float | None:
    try:
        out = subprocess.run(["du", "-sBM", str(root)], capture_output=True,
                             text=True, timeout=120).stdout
        return int(out.split("M", 1)[0]) / 1024.0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--chain-start", required=True)
    ap.add_argument("--until", action="append", default=[])
    ap.add_argument("--experiments-completed", type=int, default=0)
    ap.add_argument("--consecutive-no-improvement", type=int, default=0)
    ap.add_argument("--metric-value", type=float, default=None)
    args = ap.parse_args()

    root = args.root.resolve()
    start = dt.datetime.fromisoformat(args.chain_start.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)

    totals = {
        "wall_hours": round((now - start).total_seconds() / 3600, 3),
        "tokens_spent": tokens_since(root, start),
        "experiments_completed": args.experiments_completed,
        "consecutive_no_improvement": args.consecutive_no_improvement,
        "metric": args.metric_value,
    }

    conditions: list[tuple[str, str, str, float]] = []  # (source, key, op, value)
    for c in args.until:
        try:
            key, op, val = c.split(":")
            conditions.append(("--until", key, op, float(val)))
        except ValueError:
            print(f"bad condition: {c!r}", file=sys.stderr)
            return 2

    budget_file = root / "budget.yaml"
    budget = {}
    if budget_file.is_file():
        try:
            budget = yaml.safe_load(budget_file.read_text()) or {}
        except yaml.YAMLError:
            budget = {}
    for bkey, (key, op) in BUDGET_IMPLICIT.items():
        if budget.get(bkey) is not None:
            conditions.append(("budget.yaml", key, op, float(budget[bkey])))
    if budget.get("max_disk_gb") is not None:
        used = disk_gb(root)
        totals["disk_gb"] = used
        if used is not None and used >= float(budget["max_disk_gb"]):
            conditions.append(("budget.yaml", "disk_gb", "gte",
                               float(budget["max_disk_gb"])))
            totals.setdefault("disk_gb", used)

    tripped = []
    for source, key, op, val in conditions:
        cur = totals.get(key)
        if cur is None:
            continue
        if OPS[op](cur, val):
            tripped.append(f"{source}: {key}:{op}:{val:g} (current {cur:g})")

    print(json.dumps({"halt": bool(tripped), "tripped": tripped,
                      "totals": totals, "budget_present": bool(budget)},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
