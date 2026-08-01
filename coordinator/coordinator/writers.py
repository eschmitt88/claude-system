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


# The job-queue / decisions / session-cap writers were removed 2026-08-01
# (instruction-ablation-program, phase 1): three months of telemetry showed
# the admission layer never fired. Recover from git history if multi-project
# parallel autonomy ever needs it.
