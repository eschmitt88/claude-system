"""Read helpers for /status, /plan, and the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import connect


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def tokens_in_last(seconds: int, project: Optional[str] = None) -> dict:
    """Sum token usage over the last `seconds` seconds, optionally filtered
    by project. Returns {input, output, cache_read, cache_creation, total}."""
    since = (_now_utc() - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    where = "timestamp >= ?"
    args: list = [since]
    if project:
        where += " AND project = ?"
        args.append(project)
    with connect() as c:
        row = c.execute(
            f"""
            SELECT
                COALESCE(SUM(input_tokens),0)          AS input_tokens,
                COALESCE(SUM(output_tokens),0)         AS output_tokens,
                COALESCE(SUM(cache_read_tokens),0)     AS cache_read_tokens,
                COALESCE(SUM(cache_creation_tokens),0) AS cache_creation_tokens
            FROM token_events
            WHERE {where}
            """,
            args,
        ).fetchone()
        out = dict(row)
        out["total"] = out["input_tokens"] + out["output_tokens"] + out["cache_creation_tokens"]
        return out


def latest_hardware_sample() -> Optional[dict]:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM hardware_samples ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def queued_jobs(limit: int = 20) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY priority DESC, id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def recent_completed_jobs(limit: int = 20) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM jobs WHERE status IN ('done','deferred','failed') ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def running_job_for_project(project: str, kind: Optional[str] = None) -> Optional[dict]:
    where = "status='running' AND project=?"
    args: list = [project]
    if kind:
        where += " AND kind=?"
        args.append(kind)
    with connect() as c:
        row = c.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY id DESC LIMIT 1", args
        ).fetchone()
        return dict(row) if row else None
