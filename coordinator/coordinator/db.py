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

-- === job ledger (schedule-aware headroom) ==================================
-- Inventory of recurring jobs, derived from systemd timers + the user crontab.
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    unit              TEXT PRIMARY KEY,   -- 'foo.service' or 'cron:<slug>'
    scope             TEXT NOT NULL,      -- 'user' | 'system' | 'cron'
    description       TEXT,
    service_type      TEXT,               -- systemd Type= (oneshot/simple/...)
    schedule          TEXT,               -- OnCalendar= / cron expr / 'every 30s'
    interval_s        INTEGER,            -- for monotonic timers
    randomized_delay_s INTEGER DEFAULT 0,
    next_run          TEXT,               -- ISO UTC (from the timer itself)
    last_run          TEXT,
    next_runs_json    TEXT,               -- cached occurrences, next 7 days
    project           TEXT,               -- from ~/.claude/jobs.yaml (optional)
    notes             TEXT,
    ignored           INTEGER DEFAULT 0,
    tracked           INTEGER DEFAULT 1,  -- 0 = high-frequency monitor; runs not recorded
    updated_at        TEXT NOT NULL
);

-- One row per observed run. Populated live from cgroup accounting by the
-- poller and back-filled / refined from the journal (start, finish, result,
-- CPU time). Kept indefinitely — a few rows per job per day.
CREATE TABLE IF NOT EXISTS job_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    unit            TEXT NOT NULL,
    scope           TEXT NOT NULL,
    invocation_id   TEXT UNIQUE,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_s      REAL,
    result          TEXT NOT NULL DEFAULT 'running',  -- running|done|failed
    cpu_seconds     REAL,             -- cgroup / journal CPU time
    peak_rss_gb     REAL,             -- cgroup memory.peak (exact, per unit)
    peak_vram_gb    REAL,             -- NVML per-process, attributed by cgroup
    est_ram_gb      REAL,             -- box-level delta vs pre-run baseline
    est_vram_gb     REAL,
    avg_gpu_util    REAL,             -- box-level GPU util during the run
    n_samples       INTEGER DEFAULT 0,
    sum_gpu_util    REAL DEFAULT 0,
    source          TEXT,             -- cgroup|journal|both
    confounded      INTEGER DEFAULT 0, -- another tracked run overlapped (box deltas unreliable)
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_runs_unit ON job_runs(unit, started_at);

-- Raw per-tick per-unit samples for units that are running. Pruned at 30d.
CREATE TABLE IF NOT EXISTS job_samples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    unit          TEXT NOT NULL,
    invocation_id TEXT,
    cpu_usec      INTEGER,
    mem_bytes     INTEGER,
    mem_peak_bytes INTEGER,
    gpu_mem_mb    REAL
);
CREATE INDEX IF NOT EXISTS idx_job_samples_time ON job_samples(timestamp);

-- Expectations declared by `claude-coordinator-jobs run` for ad-hoc runs
-- (so the forecast can include a run before it has any history).
CREATE TABLE IF NOT EXISTS job_declared (
    unit        TEXT PRIMARY KEY,
    name        TEXT,
    gpu_gb      REAL,
    ram_gb      REAL,
    cores       REAL,
    hours       REAL,
    declared_at TEXT NOT NULL,
    cwd         TEXT,
    command     TEXT
);

-- Small key/value store for poller bookkeeping (last journal catch-up, ...).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
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


# Columns added after a table first shipped: (table, column, DDL type/default).
_MIGRATIONS = [
    ("scheduled_jobs", "tracked", "INTEGER DEFAULT 1"),
    ("job_runs", "confounded", "INTEGER DEFAULT 0"),
]


def init_schema() -> None:
    """Create all tables if missing, then add any columns introduced later.
    Idempotent."""
    with connect() as c:
        c.executescript(SCHEMA)
        for table, col, ddl in _MIGRATIONS:
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def prune_hardware_samples(keep_days: int = 30) -> int:
    """Delete hardware samples older than `keep_days`. Returns rows deleted.

    30 days (was 7) so job footprints can be learned from a month of
    history; ~2.9k rows/day is negligible."""
    with connect() as c:
        cur = c.execute(
            "DELETE FROM hardware_samples WHERE timestamp < datetime('now', ?)",
            (f"-{keep_days} days",),
        )
        n = cur.rowcount
        try:
            c.execute(
                "DELETE FROM job_samples WHERE timestamp < datetime('now', ?)",
                (f"-{keep_days} days",),
            )
        except sqlite3.OperationalError:
            pass  # schema not migrated yet (init runs right after install)
        return n


def get_meta(key: str, default=None):
    with connect() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
