"""Writer functions used by the Stop hook, poller, and skills."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from .db import connect


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_token_event(
    session_id: str,
    project: Optional[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    tools_used: Optional[dict] = None,
    timestamp: Optional[str] = None,
) -> int:
    with connect() as c:
        cur = c.execute(
            """
            INSERT INTO token_events
              (timestamp, session_id, project, input_tokens, output_tokens,
               cache_read_tokens, cache_creation_tokens, tools_used_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp or _now_iso(),
                session_id,
                project,
                int(input_tokens),
                int(output_tokens),
                int(cache_read_tokens),
                int(cache_creation_tokens),
                json.dumps(tools_used or {}),
            ),
        )
        return cur.lastrowid


def insert_hardware_sample(sample: dict, timestamp: Optional[str] = None) -> int:
    cols = [
        "timestamp",
        "cpu_percent",
        "ram_percent",
        "ram_used_gb",
        "ram_total_gb",
        "disk_used_gb",
        "disk_free_gb",
        "gpu_util_pct",
        "gpu_mem_used_gb",
        "gpu_mem_total_gb",
        "gpu_temp_c",
        "gpu_power_w",
    ]
    vals = [timestamp or _now_iso()] + [sample.get(k) for k in cols[1:]]
    placeholders = ",".join(["?"] * len(cols))
    with connect() as c:
        cur = c.execute(
            f"INSERT INTO hardware_samples ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        return cur.lastrowid


def declare_job(
    project: str,
    kind: str,
    description: str = "",
    est_tokens: Optional[int] = None,
    est_gpu_minutes: Optional[float] = None,
    est_vram_gb: Optional[float] = None,
    priority: int = 0,
    note: str = "",
) -> int:
    """Insert a new job row in 'queued' state. Returns job id."""
    with connect() as c:
        cur = c.execute(
            """
            INSERT INTO jobs
              (project, kind, description, est_tokens, est_gpu_minutes, est_vram_gb,
               priority, status, created_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                project,
                kind,
                description,
                est_tokens,
                est_gpu_minutes,
                est_vram_gb,
                priority,
                _now_iso(),
                note,
            ),
        )
        return cur.lastrowid


def start_job(job_id: int) -> None:
    with connect() as c:
        c.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=?",
            (_now_iso(), job_id),
        )


def complete_job(
    job_id: int,
    actual_tokens: Optional[int] = None,
    actual_gpu_minutes: Optional[float] = None,
    status: str = "done",
    note: str = "",
) -> None:
    with connect() as c:
        c.execute(
            """
            UPDATE jobs
               SET status=?, completed_at=?, actual_tokens=?, actual_gpu_minutes=?, note=COALESCE(NULLIF(?, ''), note)
             WHERE id=?
            """,
            (status, _now_iso(), actual_tokens, actual_gpu_minutes, note, job_id),
        )


def log_decision(job_id: Optional[int], verdict: str, reason: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO decisions (timestamp, job_id, verdict, reason) VALUES (?, ?, ?, ?)",
            (_now_iso(), job_id, verdict, reason),
        )


def set_session_cap(session_id: str, hard_stop_tokens: int) -> None:
    with connect() as c:
        c.execute(
            """
            INSERT INTO session_caps (session_id, hard_stop_tokens, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET hard_stop_tokens=excluded.hard_stop_tokens
            """,
            (session_id, int(hard_stop_tokens), _now_iso()),
        )


def get_session_cap(session_id: str) -> Optional[int]:
    with connect() as c:
        row = c.execute(
            "SELECT hard_stop_tokens FROM session_caps WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return int(row[0]) if row else None
