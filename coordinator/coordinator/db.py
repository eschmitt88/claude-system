"""sqlite access with WAL mode + portalocker for cross-process writes."""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator

import portalocker

from . import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS token_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,          -- ISO UTC
    session_id        TEXT NOT NULL,
    project           TEXT,                   -- project slug (may be NULL)
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    tools_used_json   TEXT                    -- tool histogram
);
CREATE INDEX IF NOT EXISTS idx_token_events_time ON token_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_token_events_project ON token_events(project);

CREATE TABLE IF NOT EXISTS hardware_samples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    cpu_percent   REAL,
    ram_percent   REAL,
    ram_used_gb   REAL,
    ram_total_gb  REAL,
    disk_used_gb  REAL,
    disk_free_gb  REAL,
    gpu_util_pct  REAL,
    gpu_mem_used_gb REAL,
    gpu_mem_total_gb REAL,
    gpu_temp_c    REAL,
    gpu_power_w   REAL
);
CREATE INDEX IF NOT EXISTS idx_hw_time ON hardware_samples(timestamp);

CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project            TEXT NOT NULL,
    kind               TEXT NOT NULL,          -- 'research', 'implement', 'iterate', 'ingest', 'score', 'digest'
    description        TEXT,
    est_tokens         INTEGER,
    est_gpu_minutes    REAL,
    est_vram_gb        REAL,
    priority           INTEGER DEFAULT 0,
    status             TEXT NOT NULL,          -- 'queued', 'running', 'done', 'deferred', 'failed'
    created_at         TEXT NOT NULL,
    started_at         TEXT,
    completed_at       TEXT,
    actual_tokens      INTEGER,
    actual_gpu_minutes REAL,
    note               TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project);

CREATE TABLE IF NOT EXISTS decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL,
    job_id     INTEGER,                        -- FK-ish, not enforced
    verdict    TEXT NOT NULL,                  -- 'admit' | 'defer'
    reason     TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS session_caps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL UNIQUE,
    hard_stop_tokens INTEGER,                  -- PreToolUse hook halts past this
    created_at    TEXT NOT NULL
);
"""


@contextlib.contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the coordinator DB in WAL mode, file-locked for writers.

    Readers don't need the lock (WAL handles concurrent reads), but
    writers take an advisory lock on ~/.claude/state.db.lock to
    serialize cross-process writes (Stop hook + poller + skills).
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = DB_PATH.with_suffix(".db.lock")
    with portalocker.Lock(str(lock_path), timeout=5):
        conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_schema() -> None:
    """Create all tables if missing. Idempotent."""
    with connect() as c:
        c.executescript(SCHEMA)


def prune_hardware_samples(keep_days: int = 7) -> int:
    """Delete hardware samples older than `keep_days`. Returns rows deleted."""
    with connect() as c:
        cur = c.execute(
            "DELETE FROM hardware_samples WHERE timestamp < datetime('now', ?)",
            (f"-{keep_days} days",),
        )
        return cur.rowcount
