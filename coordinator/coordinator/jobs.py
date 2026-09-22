"""Job ledger — schedule-aware headroom.

Answers three questions for an agent about to spend compute on a shared box:

1. **What runs here, and when?**  Inventory of recurring jobs derived from
   systemd timers (user + system) and the user crontab. Nothing is
   registered by hand; the OS already knows.
2. **What does each job cost?**  Per-run footprints learned passively:
   cgroup v2 accounting (CPU time, peak RSS) and NVML per-process VRAM
   attributed to units via /proc/<pid>/cgroup, sampled by the existing
   30s poller; start/finish/result/CPU-time back-filled from the journal.
3. **When is a window free for *my* run?**  A forecast of the next 48h
   (scheduled occurrences × learned footprints × running jobs) and a
   search for the earliest slot where a requested GPU/RAM/CPU envelope
   fits without colliding.

Advisory only — there is no admission gate. The previous gate
(``/plan`` + ``jobs`` table, removed 2026-08-01) required agents to
declare work and never fired. This layer costs the agent nothing: the
session-start hook, ``/headroom`` and the agency verdict surface it
automatically.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import statistics
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .db import connect, get_meta, set_meta

UTC = timezone.utc
CGROUP_ROOT = Path("/sys/fs/cgroup")
ANNOTATIONS_PATH = Path(os.environ.get("CLAUDE_JOBS_YAML", str(Path.home() / ".claude" / "jobs.yaml")))

# systemd journal MESSAGE_IDs (catalog): unit lifecycle events.
MSG_STARTING = "7d4958e842da4a758f6c1cdc7b36dcc5"   # "Starting X..."
MSG_STARTED = "39f53479d3a045ac8e11786248231fbf"    # "Started X" / "Finished X" (JOB_RESULT)
MSG_FAILED = "be02cf6855d2428ba40df7e9d022f03d"     # "Failed to start X"
MSG_STOPPED = "9d1aaa27d60140bd96365438aad20286"    # "Deactivated successfully" / stopped
MSG_CONSUMED = "ae8f7b866b0347b9af31fe1c80b127c0"   # "X: Consumed N CPU time"
MSG_UNIT_FAILED = "d9b373ed55a64feb8242e02dbe79a49c"  # "Failed with result '...'"

# Transient units launched via `claude-coordinator-jobs run`.
ADHOC_PREFIX = "job-"

# Footprint classification thresholds.
GPU_VRAM_GB = 1.0
GPU_UTIL_PCT = 10.0
HEAVY_CORES = 4.0
HEAVY_RAM_GB = 16.0
BURST_MAX_S = 120.0       # runs shorter than this never matter for planning
LIGHT_MAX_S = 900.0       # negligible footprint and < 15 min → hidden from timelines

# Headroom kept free for interactive sessions / the OS. Overridable via env
# (JOBS_RESERVE_VRAM_GB / JOBS_RESERVE_RAM_GB) so ~/.claude/.env can tune it.
VRAM_MARGIN_GB = float(os.environ.get("JOBS_RESERVE_VRAM_GB", "1.0"))
RAM_MARGIN_GB = float(os.environ.get("JOBS_RESERVE_RAM_GB", "12.0"))

# Priority classes for the gate. Higher rank reserves capacity against lower.
CLASS_RANK = {"production": 3, "batch": 2, "agent": 1}
DEFAULT_MAX_WAIT_H = {"production": 6.0, "batch": 12.0, "agent": 4.0}
GATE_POLL_S = 45.0
PROFILE_RUNS = 12         # newest N finished runs feed a profile
FORECAST_DAYS = 7         # occurrences cached per job
OCCURRENCE_CAP = 400
# Jobs firing more often than this are monitors/samplers: kept in the
# inventory but their runs are not recorded (they would flood the ledger —
# a 30 s sampler alone is 2,880 runs/day — and their footprint is noise).
MIN_TRACKED_PERIOD_S = 20 * 60
MAX_TRACKED_OCCURRENCES = FORECAST_DAYS * 24 * 2   # > every 30 min over the horizon
MIN_ENRICH_DURATION_S = 120.0   # box-level deltas are noise for shorter runs


# ---------------------------------------------------------------- utilities

def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _parse_systemd_ts(s: Optional[str]) -> Optional[datetime]:
    """'Wed 2026-09-16 07:20:17 UTC' → aware datetime. Empty → None.
    Non-UTC zone abbreviations are treated as the machine's local zone."""
    if not s or s in ("n/a", "0"):
        return None
    parts = s.split()
    if len(parts) < 3:
        return None
    try:
        naive = datetime.strptime(parts[1] + " " + parts[2], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    tz = parts[3] if len(parts) > 3 else ""
    if tz in ("UTC", "GMT", "Z"):
        return naive.replace(tzinfo=UTC)
    return naive.astimezone()  # naive → local → aware


_SPAN_UNITS = {
    "us": 1e-6, "usec": 1e-6, "ms": 1e-3, "msec": 1e-3,
    "s": 1, "sec": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
}


def _parse_span(s: Optional[str]) -> float:
    """systemd time span ('10min', '1h 30min', '2d', '0', 'infinity') → seconds."""
    if not s or s in ("0", "infinity", "[not set]"):
        return 0.0
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)\s*([a-zA-Zµ]*)", s):
        total += float(num) * _SPAN_UNITS.get(unit or "s", 0)
    return total


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 or r.stdout else ""


def _systemctl_json(args: list[str], user: bool) -> list[dict]:
    cmd = ["systemctl"] + (["--user"] if user else []) + args + ["--output=json", "--no-pager"]
    out = _run(cmd)
    if not out.strip():
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []


def _systemctl_show(units: list[str], props: list[str], user: bool) -> dict[str, dict]:
    """Batch `systemctl show` → {unit_id: {prop: value}}. Multi-valued props
    (TimersCalendar/TimersMonotonic) are joined with '\\n'."""
    if not units:
        return {}
    cmd = ["systemctl"] + (["--user"] if user else []) + ["show", *units, "-p", ",".join(props)]
    out = _run(cmd)
    result: dict[str, dict] = {}
    for block in out.strip().split("\n\n"):
        d: dict[str, str] = {}
        for line in block.splitlines():
            k, _, v = line.partition("=")
            d[k] = (d[k] + "\n" + v) if k in d else v
        if d.get("Id"):
            result[d["Id"]] = d
    return result


def _median(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _p90(xs: list[float]) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    if len(xs) < 3:
        return xs[-1]
    k = max(0, min(len(xs) - 1, round(0.9 * (len(xs) - 1))))
    return xs[k]


def _cpu_count() -> int:
    return os.cpu_count() or 1


# ------------------------------------------------------------- annotations

def load_annotations() -> dict:
    """Optional operator notes in ~/.claude/jobs.yaml (untracked). Shape:

        jobs:
          foo.service: {project: foo, notes: "...", ignore: false,
                        expect: {gpu_gb: 8, ram_gb: 20, cores: 4, hours: 1}}
    """
    if not ANNOTATIONS_PATH.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(ANNOTATIONS_PATH.read_text()) or {}
    except Exception:
        return {}
    return data.get("jobs", {}) or {}


# --------------------------------------------------------------- inventory

def _crontab_jobs() -> list[dict]:
    """User crontab entries → pseudo-units 'cron:<slug>'."""
    out = _run(["crontab", "-l"])
    jobs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" in line.split()[0]:
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        expr, cmd = " ".join(parts[:5]), parts[5]
        first = shlex.split(cmd)[0] if cmd else cmd
        slug = Path(first).stem or first
        jobs.append({
            "unit": f"cron:{slug}", "scope": "cron", "description": cmd[:160],
            "service_type": "cron", "schedule": expr, "interval_s": None,
            "randomized_delay_s": 0, "next_run": None, "last_run": None,
        })
    return jobs


def _timer_jobs(user: bool) -> list[dict]:
    timers = _systemctl_json(["list-timers", "--all"], user=user)
    if not timers:
        return []
    tnames = [t["unit"] for t in timers if t.get("unit")]
    snames = [t["activates"] for t in timers if t.get("activates")]
    tprops = _systemctl_show(tnames, ["Id", "TimersCalendar", "TimersMonotonic", "RandomizedDelayUSec", "Unit"], user)
    sprops = _systemctl_show(snames, ["Id", "Description", "Type"], user)
    scope = "user" if user else "system"
    jobs = []
    for t in timers:
        tp = tprops.get(t.get("unit", ""), {})
        sp = sprops.get(t.get("activates", ""), {})
        cal = re.findall(r"OnCalendar=(.*?) ;", tp.get("TimersCalendar", ""))
        mono = re.findall(r"On(UnitActive|UnitInactive|Active)USec=(.*?) ;", tp.get("TimersMonotonic", ""))
        schedule, interval = None, None
        if cal:
            schedule = cal[0]
        elif mono:
            interval = int(_parse_span(mono[0][1]))
            schedule = f"every {mono[0][1]}"
        nxt = t.get("next") or 0
        last = t.get("last") or 0
        jobs.append({
            "unit": t.get("activates"), "scope": scope,
            "description": sp.get("Description", ""), "service_type": sp.get("Type", ""),
            "schedule": schedule, "interval_s": interval,
            "randomized_delay_s": int(_parse_span(tp.get("RandomizedDelayUSec", "0"))),
            "next_run": _iso(datetime.fromtimestamp(nxt / 1e6, UTC)) if nxt else None,
            "last_run": _iso(datetime.fromtimestamp(last / 1e6, UTC)) if last else None,
        })
    return jobs


def discover_jobs() -> list[dict]:
    """Live inventory from systemd (user + system) and crontab."""
    return _timer_jobs(user=True) + _timer_jobs(user=False) + _crontab_jobs()


# ------------------------------------------------------------- occurrences

def _calendar_occurrences(spec: str, base: datetime, n: int) -> list[datetime]:
    out = _run(["systemd-analyze", "calendar", f"--iterations={n}",
                f"--base-time={base.strftime('%Y-%m-%d %H:%M:%S UTC')}", spec], timeout=5)
    res = []
    for line in out.splitlines():
        if "Next elapse:" in line or "Iteration #" in line:
            dt = _parse_systemd_ts(line.split(":", 1)[1].strip())
            if dt:
                res.append(dt)
    return res


def _cron_occurrences(expr: str, base: datetime, until: datetime) -> list[datetime]:
    try:
        from croniter import croniter
    except ImportError:
        return []
    try:
        it = croniter(expr, base.astimezone())
    except Exception:
        return []
    res = []
    while len(res) < OCCURRENCE_CAP:
        dt = it.get_next(datetime)
        if dt.astimezone(UTC) > until:
            break
        res.append(dt.astimezone(UTC))
    return res


def occurrences(job: dict, base: Optional[datetime] = None, days: int = FORECAST_DAYS) -> list[datetime]:
    """Expected trigger times for a job within [base, base+days]."""
    base = base or _now()
    until = base + timedelta(days=days)
    sched = job.get("schedule") or ""
    if job.get("scope") == "cron":
        return _cron_occurrences(sched, base, until)
    if job.get("interval_s"):
        nxt = _parse_iso(job.get("next_run")) or base
        step = timedelta(seconds=max(1, job["interval_s"]))
        res, t = [], nxt
        while t <= until and len(res) < OCCURRENCE_CAP:
            if t >= base:
                res.append(t)
            t += step
        return res
    if sched:
        # Ask for enough iterations to cover the horizon for hourly jobs;
        # trim to the window. Daily/weekly jobs stop early.
        n = min(OCCURRENCE_CAP, max(8, days * 24 + 1)) if "*:" in sched or "/" in sched else max(8, days + 1)
        return [d for d in _calendar_occurrences(sched, base, n) if base <= d <= until]
    nxt = _parse_iso(job.get("next_run"))
    return [nxt] if nxt and base <= nxt <= until else []


def _is_high_frequency(job: dict, occ_list: list) -> bool:
    """Monitors/samplers: period shorter than MIN_TRACKED_PERIOD_S, judged
    from the timer interval or the spacing of the first two occurrences."""
    if job.get("interval_s") and job["interval_s"] < MIN_TRACKED_PERIOD_S:
        return True
    if len(occ_list) > MAX_TRACKED_OCCURRENCES:
        return True
    if len(occ_list) >= 2:
        a = occ_list[0] if isinstance(occ_list[0], datetime) else _parse_iso(occ_list[0])
        b = occ_list[1] if isinstance(occ_list[1], datetime) else _parse_iso(occ_list[1])
        if a and b and (b - a).total_seconds() < MIN_TRACKED_PERIOD_S:
            return True
    return False


def sync_inventory(force_occurrences: bool = False) -> int:
    """Refresh scheduled_jobs from the OS. Occurrence lists are recomputed
    every 10 minutes (they involve a subprocess per calendar spec)."""
    jobs = discover_jobs()
    ann = load_annotations()
    now = _now()
    last = _parse_iso(get_meta("jobs.occurrences_at"))
    recompute = force_occurrences or last is None or (now - last) > timedelta(minutes=10)
    with connect() as c:
        existing = {r["unit"]: dict(r) for r in c.execute("SELECT * FROM scheduled_jobs")}
        seen = set()
        for j in jobs:
            unit = j.get("unit")
            if not unit:
                continue
            seen.add(unit)
            a = ann.get(unit, {}) or {}
            prev = existing.get(unit, {})
            if recompute or not prev.get("next_runs_json") or prev.get("schedule") != j.get("schedule"):
                occ_list = occurrences(j, now)
                occ = json.dumps([_iso(d) for d in occ_list])
            else:
                occ = prev["next_runs_json"]
                try:
                    occ_list = json.loads(occ)
                except json.JSONDecodeError:
                    occ_list = []
            high_freq = _is_high_frequency(j, occ_list)
            tracked = 0 if (high_freq and not a.get("track")) else 1
            c.execute(
                """INSERT INTO scheduled_jobs(unit, scope, description, service_type, schedule,
                       interval_s, randomized_delay_s, next_run, last_run, next_runs_json,
                       project, notes, ignored, tracked, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(unit) DO UPDATE SET scope=excluded.scope,
                       description=excluded.description, service_type=excluded.service_type,
                       schedule=excluded.schedule, interval_s=excluded.interval_s,
                       randomized_delay_s=excluded.randomized_delay_s, next_run=excluded.next_run,
                       last_run=excluded.last_run, next_runs_json=excluded.next_runs_json,
                       project=excluded.project, notes=excluded.notes, ignored=excluded.ignored,
                       tracked=excluded.tracked, updated_at=excluded.updated_at""",
                (unit, j["scope"], j.get("description"), j.get("service_type"), j.get("schedule"),
                 j.get("interval_s"), j.get("randomized_delay_s", 0), j.get("next_run"), j.get("last_run"),
                 occ, a.get("project"), a.get("notes"), 1 if a.get("ignore") else 0, tracked, _iso(now)),
            )
        gone = set(existing) - seen
        if gone:
            c.executemany("DELETE FROM scheduled_jobs WHERE unit = ?", [(u,) for u in gone])
        # Runs recorded for units that are (now) untracked are noise — drop them.
        c.execute("DELETE FROM job_runs WHERE unit IN (SELECT unit FROM scheduled_jobs WHERE tracked = 0)")
        c.execute("DELETE FROM job_samples WHERE unit IN (SELECT unit FROM scheduled_jobs WHERE tracked = 0)")
    if recompute:
        set_meta("jobs.occurrences_at", _iso(now))
    return len(jobs)


def inventory(tracked_only: bool = False) -> list[dict]:
    q = "SELECT * FROM scheduled_jobs" + (" WHERE tracked = 1" if tracked_only else "") + " ORDER BY scope, unit"
    with connect() as c:
        rows = [dict(r) for r in c.execute(q)]
    for r in rows:
        try:
            r["next_runs"] = json.loads(r.pop("next_runs_json") or "[]")
        except json.JSONDecodeError:
            r["next_runs"] = []
    return rows


# ---------------------------------------------------------- live sampling

def _gpu_procs() -> list[dict]:
    """[{pid, vram_mb, cgroup, unit}] for every process holding GPU memory."""
    procs: list[dict] = []
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        try:
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                plist = []
                for fn in ("nvmlDeviceGetComputeRunningProcesses", "nvmlDeviceGetGraphicsRunningProcesses"):
                    try:
                        plist += getattr(pynvml, fn)(h)
                    except pynvml.NVMLError:
                        pass
                for p in plist:
                    mem = getattr(p, "usedGpuMemory", None)
                    procs.append({"pid": int(p.pid), "vram_mb": (mem or 0) / (1024 ** 2)})
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return []
    merged: dict[int, dict] = {}
    for p in procs:  # a pid can appear on several handles/lists
        m = merged.setdefault(p["pid"], {"pid": p["pid"], "vram_mb": 0.0})
        m["vram_mb"] = max(m["vram_mb"], p["vram_mb"])
    for m in merged.values():
        cg = ""
        try:
            for line in Path(f"/proc/{m['pid']}/cgroup").read_text().splitlines():
                if line.startswith("0::"):
                    cg = line[3:].strip()
        except OSError:
            pass
        m["cgroup"] = cg
        m["unit"] = cg.rsplit("/", 1)[-1] if cg else ""
        try:
            m["comm"] = Path(f"/proc/{m['pid']}/comm").read_text().strip()
        except OSError:
            m["comm"] = ""
    return list(merged.values())


def _read_cgroup(cg: str) -> dict:
    base = CGROUP_ROOT / cg.lstrip("/")
    """cpu_usec (cumulative), mem_bytes = ANONYMOUS memory (memory.stat
    anon + shmem: what the job really holds; page cache is reclaimable and
    would inflate the footprint by tens of GB), mem_peak_bytes = kernel
    memory.peak (cache-inclusive, kept for reference only)."""
    out = {"cpu_usec": None, "mem_bytes": None, "mem_peak_bytes": None}
    try:
        for line in (base / "cpu.stat").read_text().splitlines():
            if line.startswith("usage_usec"):
                out["cpu_usec"] = int(line.split()[1])
        anon = None
        for line in (base / "memory.stat").read_text().splitlines():
            k, _, v = line.partition(" ")
            if k in ("anon", "shmem"):
                anon = (anon or 0) + int(v)
        out["mem_bytes"] = anon if anon is not None else int((base / "memory.current").read_text())
        pk = base / "memory.peak"
        if pk.exists():
            out["mem_peak_bytes"] = int(pk.read_text())
    except (OSError, ValueError):
        pass
    return out


def _active_tracked(tracked: set[str], user: bool) -> dict[str, dict]:
    """Active services we care about in one scope, with show() props."""
    active = _systemctl_json(["list-units", "--type=service", "--state=active,activating,deactivating"], user=user)
    names = [u["unit"] for u in active
             if u.get("unit") and (u["unit"] in tracked or u["unit"].startswith(ADHOC_PREFIX))]
    return _systemctl_show(
        names, ["Id", "InvocationID", "ExecMainStartTimestamp", "ActiveEnterTimestamp",
                "ControlGroup", "Result", "ActiveState", "Description"], user)


def sample_running(hw: Optional[dict] = None) -> list[dict]:
    """One poller tick: snapshot every tracked running unit into job_samples,
    upsert its job_runs row, finalize runs that have ended. Returns the list
    of running rows (used by `now`)."""
    now = _now()
    inv = {r["unit"]: r for r in inventory(tracked_only=True)}
    tracked = {u for u in inv if not u.startswith("cron:")}
    gpu = _gpu_procs()
    gpu_util = (hw or {}).get("gpu_util_pct")
    running: list[dict] = []
    live_inv_ids: set[str] = set()

    gate = gate_state()
    for user in (True, False):
        scope = "user" if user else "system"
        for uid, p in _active_tracked(tracked, user).items():
            g = gate.get(uid)
            if g and g["state"] == "waiting":
                continue  # queued behind the gate: not running yet, no footprint to learn
            cg = p.get("ControlGroup") or ""
            inv_id = p.get("InvocationID") or f"{uid}@{p.get('ExecMainStartTimestamp')}"
            started = (_parse_iso(g["started_at"]) if g and g.get("started_at") else None) or \
                _parse_systemd_ts(p.get("ExecMainStartTimestamp")) or \
                _parse_systemd_ts(p.get("ActiveEnterTimestamp")) or now
            cgs = _read_cgroup(cg) if cg else {}
            vram_mb = sum(g["vram_mb"] for g in gpu if cg and g["cgroup"].startswith(cg))
            live_inv_ids.add(inv_id)
            row = {
                "unit": uid, "scope": scope, "invocation_id": inv_id, "started_at": _iso(started),
                "cpu_usec": cgs.get("cpu_usec"), "mem_bytes": cgs.get("mem_bytes"),
                "mem_peak_bytes": cgs.get("mem_peak_bytes"), "gpu_mem_mb": vram_mb,
                "description": p.get("Description", ""),
            }
            running.append(row)
            with connect() as c:
                c.execute(
                    "INSERT INTO job_samples(timestamp, unit, invocation_id, cpu_usec, mem_bytes, mem_peak_bytes, gpu_mem_mb)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (_iso(now), uid, inv_id, row["cpu_usec"], row["mem_bytes"], row["mem_peak_bytes"], vram_mb))
                c.execute(
                    """INSERT INTO job_runs(unit, scope, invocation_id, started_at, result, cpu_seconds,
                           peak_rss_gb, peak_vram_gb, n_samples, sum_gpu_util, source, updated_at)
                       VALUES (?,?,?,?, 'running', ?,?,?, 1, ?, 'cgroup', ?)
                       ON CONFLICT(invocation_id) DO UPDATE SET
                           cpu_seconds = COALESCE(excluded.cpu_seconds, job_runs.cpu_seconds),
                           peak_rss_gb = MAX(COALESCE(job_runs.peak_rss_gb, 0), COALESCE(excluded.peak_rss_gb, 0)),
                           peak_vram_gb = MAX(COALESCE(job_runs.peak_vram_gb, 0), COALESCE(excluded.peak_vram_gb, 0)),
                           n_samples = job_runs.n_samples + 1,
                           sum_gpu_util = job_runs.sum_gpu_util + excluded.sum_gpu_util,
                           source = CASE WHEN job_runs.source = 'journal' THEN 'both' ELSE job_runs.source END,
                           updated_at = excluded.updated_at""",
                    (uid, scope, inv_id, _iso(started),
                     (row["cpu_usec"] or 0) / 1e6 if row["cpu_usec"] is not None else None,
                     (row["mem_bytes"] or 0) / 1e9,   # anon; peak = max over samples
                     vram_mb / 1024.0, float(gpu_util or 0.0), _iso(now)))

    # Finalize runs the cgroup path saw earlier that are no longer active.
    with connect() as c:
        stale = [dict(r) for r in c.execute(
            "SELECT id, unit, scope, invocation_id, started_at FROM job_runs WHERE result = 'running'")]
    for r in stale:
        if r["invocation_id"] in live_inv_ids:
            continue
        props = _systemctl_show([r["unit"]], ["Id", "InvocationID", "Result", "ActiveState"], r["scope"] == "user")
        p = props.get(r["unit"], {})
        if p.get("ActiveState") in ("active", "activating", "deactivating") and p.get("InvocationID") == r["invocation_id"]:
            continue  # still running (e.g. show/list race) — leave it
        result = "done"
        if p.get("InvocationID") == r["invocation_id"] and p.get("Result") not in ("success", "", None):
            result = "failed"
        _finalize_run(r["id"], now, result)
    _expire_gate_rows()
    _enrich_from_hardware(limit=20)
    return running


def _finalize_run(run_id: int, finished: datetime, result: str) -> None:
    with connect() as c:
        row = c.execute("SELECT started_at, finished_at FROM job_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return
        started = _parse_iso(row["started_at"]) or finished
        fin = _parse_iso(row["finished_at"]) or finished
        c.execute(
            "UPDATE job_runs SET finished_at = ?, duration_s = ?, result = ?, "
            "avg_gpu_util = CASE WHEN n_samples > 0 THEN sum_gpu_util / n_samples ELSE avg_gpu_util END, "
            "updated_at = ? WHERE id = ?",
            (_iso(fin), max(0.0, (fin - started).total_seconds()), result, _iso(finished), run_id))


# ------------------------------------------------------- journal catch-up

def _journal_events(since: datetime) -> list[dict]:
    cmd = ["journalctl", "-o", "json", "--no-pager", "--since", since.strftime("%Y-%m-%d %H:%M:%S UTC")]
    ids = [MSG_STARTING, MSG_STARTED, MSG_FAILED, MSG_STOPPED, MSG_CONSUMED, MSG_UNIT_FAILED]
    for i, mid in enumerate(ids):
        if i:
            cmd.append("+")
        cmd.append(f"MESSAGE_ID={mid}")
    out = _run(cmd, timeout=60)
    events = []
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        unit = d.get("USER_UNIT") or d.get("UNIT") or ""
        inv = d.get("USER_INVOCATION_ID") or d.get("INVOCATION_ID") or ""
        if not unit or not inv:
            continue
        ts = d.get("__REALTIME_TIMESTAMP")
        events.append({
            "unit": unit, "inv": inv, "mid": d.get("MESSAGE_ID"),
            "ts": datetime.fromtimestamp(int(ts) / 1e6, UTC) if ts else None,
            "job_result": d.get("JOB_RESULT"), "job_type": d.get("JOB_TYPE"),
            "cpu_nsec": d.get("CPU_USAGE_NSEC"), "mem_peak": d.get("MEMORY_PEAK"),
            "scope": "user" if d.get("USER_UNIT") else "system",
        })
    return events


def backfill_from_journal(days: Optional[float] = None) -> int:
    """Create/refine job_runs from journal lifecycle events since the last
    catch-up (or `days` back). Returns number of runs touched."""
    now = _now()
    if days is not None:
        since = now - timedelta(days=days)
    else:
        last = _parse_iso(get_meta("jobs.journal_at"))
        since = (last - timedelta(hours=2)) if last else now - timedelta(days=14)
    inv = {r["unit"]: r for r in inventory(tracked_only=True)}
    tracked = {u for u in inv if not u.startswith("cron:")}
    events = [e for e in _journal_events(since)
              if e["ts"] and (e["unit"] in tracked or e["unit"].startswith(ADHOC_PREFIX))]
    by_inv: dict[str, list[dict]] = {}
    for e in events:
        by_inv.setdefault(e["inv"], []).append(e)

    touched = 0
    with connect() as c:
        for inv_id, evs in by_inv.items():
            evs.sort(key=lambda e: e["ts"])
            unit = evs[0]["unit"]
            scope = evs[0]["scope"]
            stype = (inv.get(unit) or {}).get("service_type") or ""
            starts = [e["ts"] for e in evs if e["mid"] == MSG_STARTING]
            if not starts and stype == "oneshot":
                continue  # finish without a start in-window (started before `since`)
            started = starts[0] if starts else evs[0]["ts"]
            failed = any(e["mid"] in (MSG_FAILED, MSG_UNIT_FAILED) or e.get("job_result") == "failed" for e in evs)
            fin_ts = None
            for e in evs:
                if e["mid"] in (MSG_CONSUMED, MSG_STOPPED, MSG_FAILED, MSG_UNIT_FAILED):
                    fin_ts = e["ts"]
                elif e["mid"] == MSG_STARTED and (stype == "oneshot" or e.get("job_type") == "stop"):
                    fin_ts = e["ts"]
            cpu_s = next((int(e["cpu_nsec"]) / 1e9 for e in evs if e.get("cpu_nsec")), None)
            mem_peak = next((int(e["mem_peak"]) / 1e9 for e in evs if e.get("mem_peak")), None)
            result = "failed" if failed else ("done" if fin_ts else "running")
            dur = (fin_ts - started).total_seconds() if fin_ts else None
            c.execute(
                """INSERT INTO job_runs(unit, scope, invocation_id, started_at, finished_at, duration_s,
                       result, cpu_seconds, peak_rss_gb, source, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?, 'journal', ?)
                   ON CONFLICT(invocation_id) DO UPDATE SET
                       started_at = MIN(job_runs.started_at, excluded.started_at),
                       finished_at = COALESCE(excluded.finished_at, job_runs.finished_at),
                       duration_s = COALESCE(excluded.duration_s, job_runs.duration_s),
                       result = CASE WHEN excluded.result = 'running' THEN job_runs.result ELSE excluded.result END,
                       cpu_seconds = COALESCE(excluded.cpu_seconds, job_runs.cpu_seconds),
                       peak_rss_gb = MAX(COALESCE(job_runs.peak_rss_gb, 0), COALESCE(excluded.peak_rss_gb, 0)),
                       source = CASE WHEN job_runs.source = 'cgroup' THEN 'both' ELSE job_runs.source END,
                       updated_at = excluded.updated_at""",
                (unit, scope, inv_id, _iso(started), _iso(fin_ts), dur, result, cpu_s, mem_peak, _iso(now)))
            touched += 1
    set_meta("jobs.journal_at", _iso(now))
    _enrich_from_hardware(limit=5000)
    return touched


def _enrich_from_hardware(limit: int = 50) -> None:
    """For finished runs lacking box-level context, estimate RAM/VRAM deltas
    vs the 10 minutes before the run, plus mean GPU util.

    Attribution rule for box-level numbers: jobs already running when this
    one started are inside the baseline, so they cancel out. Jobs that START
    inside this run's window do not — so the measurement window is cut at
    the first such start ("clean prefix"). If the clean prefix is shorter
    than MIN_ENRICH_DURATION_S the run is flagged `confounded` and profiles
    only use it when nothing better exists."""
    with connect() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, unit, started_at, finished_at, duration_s FROM job_runs WHERE result != 'running' "
            "AND finished_at IS NOT NULL AND est_ram_gb IS NULL ORDER BY id DESC LIMIT ?", (limit,))]
        for r in rows:
            s, f = r["started_at"], r["finished_at"]
            if (r["duration_s"] or 0) < MIN_ENRICH_DURATION_S:
                # Too short for 30 s box-level samples to say anything; mark done.
                c.execute("UPDATE job_runs SET est_ram_gb = 0, est_vram_gb = 0 WHERE id = ?", (r["id"],))
                continue
            first_other = c.execute(
                "SELECT MIN(started_at) t FROM job_runs WHERE id != ? AND unit != ? AND result != 'running' "
                "AND started_at > ? AND started_at < ? AND (duration_s IS NULL OR duration_s >= ?)",
                (r["id"], r["unit"], s, f, MIN_ENRICH_DURATION_S)).fetchone()["t"]
            f_eff, confounded = f, 0
            if first_other:
                prefix = ((_parse_iso(first_other) or _parse_iso(f)) - _parse_iso(s)).total_seconds()
                if prefix >= MIN_ENRICH_DURATION_S:
                    f_eff = first_other
                else:
                    confounded = 1
            # Bounds are built in Python: stored timestamps are ISO with 'T'/'Z',
            # while sqlite's datetime() emits a space separator — mixing the two
            # in a string comparison silently widens the window.
            base_from = _iso(_parse_iso(s) - timedelta(minutes=10))
            base = c.execute(
                "SELECT AVG(ram_used_gb) ram, AVG(gpu_mem_used_gb) vram FROM hardware_samples "
                "WHERE timestamp >= ? AND timestamp < ?", (base_from, s)).fetchone()
            dur = c.execute(
                "SELECT MAX(ram_used_gb) ram, MAX(gpu_mem_used_gb) vram, AVG(gpu_util_pct) gpu, "
                "AVG(cpu_percent) cpu, COUNT(*) n FROM hardware_samples WHERE timestamp >= ? AND timestamp <= ?",
                (s, f_eff)).fetchone()
            if not dur or not dur["n"]:
                # Samples already pruned: mark as attempted so we don't retry forever.
                fin = _parse_iso(f)
                if fin and (_now() - fin) > timedelta(days=31):
                    c.execute("UPDATE job_runs SET est_ram_gb = -1 WHERE id = ?", (r["id"],))
                continue
            est_ram = max(0.0, (dur["ram"] or 0) - (base["ram"] or dur["ram"] or 0)) if base else None
            est_vram = max(0.0, (dur["vram"] or 0) - (base["vram"] or dur["vram"] or 0)) if base else None
            c.execute(
                "UPDATE job_runs SET est_ram_gb = ?, est_vram_gb = ?, confounded = ?, "
                "avg_gpu_util = COALESCE(CASE WHEN n_samples > 0 THEN sum_gpu_util / n_samples END, ?) WHERE id = ?",
                (est_ram, est_vram, confounded, dur["gpu"], r["id"]))


# ---------------------------------------------------------------- profiles

@dataclass
class Footprint:
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    cores: float = 0.0
    gpu_util: float = 0.0
    duration_s: float = 0.0        # p90
    duration_med_s: float = 0.0
    n_runs: int = 0
    klass: str = "unknown"
    source: str = "none"           # history|declared|annotation|none

    def as_dict(self) -> dict:
        return asdict(self)


def classify(fp: Footprint) -> str:
    """'gpu', 'cpu', 'ram' (joined with '+') for jobs that matter when
    planning; 'light' for bursts and negligible jobs (hidden from timelines);
    'long-light' for negligible-footprint jobs that nonetheless occupy the
    box for a while (shown as context)."""
    if fp.duration_s < BURST_MAX_S:
        return "light"
    tags = []
    if fp.vram_gb >= GPU_VRAM_GB or fp.gpu_util >= GPU_UTIL_PCT:
        tags.append("gpu")
    if fp.cores >= HEAVY_CORES:
        tags.append("cpu")
    if fp.ram_gb >= HEAVY_RAM_GB:
        tags.append("ram")
    if tags:
        return "+".join(tags)
    return "light" if fp.duration_s < LIGHT_MAX_S else "long-light"


def is_heavy(fp: Footprint) -> bool:
    return fp.klass not in ("light", "long-light", "unknown")


def runs_for(unit: str, limit: int = PROFILE_RUNS, finished_only: bool = True) -> list[dict]:
    q = "SELECT * FROM job_runs WHERE unit = ?"
    if finished_only:
        q += " AND result != 'running' AND duration_s IS NOT NULL"
    q += " ORDER BY started_at DESC LIMIT ?"
    with connect() as c:
        return [dict(r) for r in c.execute(q, (unit, limit))]


def profile(unit: str, annotations: Optional[dict] = None) -> dict:
    """Learned footprint for a unit + reliability stats."""
    ann = (annotations if annotations is not None else load_annotations()).get(unit, {}) or {}
    runs = runs_for(unit)
    ok = [r for r in runs if r["result"] == "done"]
    fp = Footprint()
    if ok:
        durs = [r["duration_s"] for r in ok if r["duration_s"] is not None and r["duration_s"] > 0]
        # Exact per-unit numbers (live cgroup/NVML) are always usable; box-level
        # deltas only from runs that did not overlap another tracked job —
        # unless that leaves nothing, in which case fall back to all.
        def _clean(r):
            return bool(r.get("peak_vram_gb") or r.get("peak_rss_gb")) or not r.get("confounded")
        exact = [r for r in ok if r.get("source") in ("cgroup", "both")]
        # Once live-attributed runs exist, they alone define RAM/VRAM: box-level
        # deltas can be polluted by whatever else touched the GPU that hour.
        base = exact or [r for r in ok if _clean(r)] or ok
        vram = [(r["peak_vram_gb"] if r["peak_vram_gb"] else r["est_vram_gb"]) for r in base]
        ram = [(r["peak_rss_gb"] if r["peak_rss_gb"] else r["est_ram_gb"]) for r in base]
        ram = [x for x in ram if x is not None and x >= 0]
        cores = [r["cpu_seconds"] / r["duration_s"] for r in ok
                 if r["cpu_seconds"] and r["duration_s"] and r["duration_s"] > 30]
        fp = Footprint(
            vram_gb=_p90([v for v in vram if v is not None]) or 0.0,
            ram_gb=_p90(ram) or 0.0,
            cores=_median(cores) or 0.0,
            gpu_util=_median([r["avg_gpu_util"] for r in base if r["avg_gpu_util"] is not None]) or 0.0,
            duration_s=_p90(durs) or 0.0,
            duration_med_s=_median(durs) or 0.0,
            n_runs=len(ok), source="history",
        )
    exp = ann.get("expect") or {}
    if exp and (not ok or ann.get("prefer_expect")):
        fp = Footprint(vram_gb=float(exp.get("gpu_gb", 0)), ram_gb=float(exp.get("ram_gb", 0)),
                       cores=float(exp.get("cores", 0)), gpu_util=100.0 if exp.get("gpu_gb") else 0.0,
                       duration_s=float(exp.get("hours", 0)) * 3600, duration_med_s=float(exp.get("hours", 0)) * 3600,
                       n_runs=len(ok), source="annotation")
    fp.klass = classify(fp)
    # Reliability: consecutive failures ending at the newest run.
    streak = 0
    for r in runs:
        if r["result"] == "failed":
            streak += 1
        else:
            break
    return {
        "unit": unit, "footprint": fp.as_dict(),
        "n_runs": len(runs), "n_failed": sum(1 for r in runs if r["result"] == "failed"),
        "fail_streak": streak,
        "last_run": runs[0]["started_at"] if runs else None,
        "last_result": runs[0]["result"] if runs else None,
        "cpu_seconds_med": _median([r["cpu_seconds"] for r in ok if r["cpu_seconds"]]),
        "n_confounded": sum(1 for r in ok if r.get("confounded") and not (r.get("peak_vram_gb") or r.get("peak_rss_gb"))),
        "project": ann.get("project"), "notes": ann.get("notes"),
    }


def inventory_with_profiles() -> list[dict]:
    ann = load_annotations()
    out = []
    for j in inventory():
        p = profile(j["unit"], ann)
        out.append({**j, **{k: v for k, v in p.items() if k != "unit"}})
    return out


# ---------------------------------------------------------------- forecast

@dataclass
class Window:
    unit: str
    start: datetime
    end: datetime
    footprint: Footprint
    kind: str = "scheduled"         # scheduled|running|declared
    jitter_s: float = 0.0
    description: str = ""
    klass: str = "batch"            # gate priority class

    def as_dict(self) -> dict:
        return {"unit": self.unit, "start": _iso(self.start), "end": _iso(self.end),
                "kind": self.kind, "jitter_s": self.jitter_s, "description": self.description,
                "class": self.klass, "footprint": self.footprint.as_dict()}


def job_class(unit: str, ann: Optional[dict] = None) -> str:
    """Gate priority class from ~/.claude/jobs.yaml; ad-hoc `job-*` units are
    `agent`, everything else defaults to `batch`."""
    a = (ann if ann is not None else load_annotations()).get(unit, {}) or {}
    if a.get("class") in CLASS_RANK:
        return a["class"]
    return "agent" if unit.startswith(ADHOC_PREFIX) else "batch"


def _running_windows(now: datetime, ann: dict) -> list[Window]:
    """Jobs occupying the box right now: poller-observed running runs merged
    with gate leases (a lease is authoritative the instant it is written,
    before the poller's next tick — that closes the two-jobs-start-at-once
    race). Envelope = max(lease, learned/observed)."""
    with connect() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT unit, scope, started_at, peak_vram_gb, peak_rss_gb, cpu_seconds FROM job_runs WHERE result = 'running'")]
        declared = {d["unit"]: dict(d) for d in c.execute("SELECT * FROM job_declared")}
    leases = {u: g for u, g in gate_state().items() if g["state"] == "running"}
    seen = {r["unit"] for r in rows}
    for u, g in leases.items():
        if u not in seen:
            rows.append({"unit": u, "scope": "user", "started_at": g.get("started_at") or g["requested_at"],
                         "peak_vram_gb": None, "peak_rss_gb": None, "cpu_seconds": None})
    out = []
    for r in rows:
        started = _parse_iso(r["started_at"]) or now
        p = profile(r["unit"], ann)
        fp = Footprint(**p["footprint"])
        d = declared.get(r["unit"])
        if d and fp.n_runs == 0:
            fp = Footprint(vram_gb=d.get("gpu_gb") or 0, ram_gb=d.get("ram_gb") or 0, cores=d.get("cores") or 0,
                           gpu_util=100.0 if d.get("gpu_gb") else 0.0, duration_s=(d.get("hours") or 1) * 3600,
                           duration_med_s=(d.get("hours") or 1) * 3600, source="declared")
            fp.klass = classify(fp)
        # Observed-so-far and the lease both beat the prior where larger.
        g = leases.get(r["unit"])
        fp.vram_gb = max(fp.vram_gb, r.get("peak_vram_gb") or 0, (g or {}).get("gpu_gb") or 0)
        fp.ram_gb = max(fp.ram_gb, r.get("peak_rss_gb") or 0, (g or {}).get("ram_gb") or 0)
        fp.cores = max(fp.cores, (g or {}).get("cores") or 0)
        if g and g.get("class"):
            fp.source = f"lease:{g['class']}"
        elapsed = (now - started).total_seconds()
        expected = fp.duration_s or ((g or {}).get("hours") or 1) * 3600.0
        end = started + timedelta(seconds=max(expected, elapsed + 300))  # never "already over"
        out.append(Window(r["unit"], started, end, fp, kind="running", klass=job_class(r["unit"], ann)))
    return out


def forecast(hours: float = 24.0, include_light: bool = False, now: Optional[datetime] = None) -> list[Window]:
    """Predicted busy windows in [now, now+hours], running jobs first."""
    now = now or _now()
    until = now + timedelta(hours=hours)
    ann = load_annotations()
    wins = _running_windows(now, ann)
    running_units = {w.unit for w in wins}
    for j in inventory():
        if j.get("ignored") or not j.get("tracked", 1):
            continue
        p = profile(j["unit"], ann)
        fp = Footprint(**p["footprint"])
        if not include_light and fp.klass == "light":
            continue
        if fp.n_runs == 0 and fp.source == "none":
            # No history and no annotation: only surface if it's a long-running
            # ad-hoc declared unit (handled above) — otherwise unknown cost.
            if not include_light:
                continue
        dur = fp.duration_s or (600.0 if include_light else 0.0)
        for s in j.get("next_runs", []):
            st = _parse_iso(s)
            if not st or st > until or st < now - timedelta(seconds=dur):
                continue
            if j["unit"] in running_units and st <= now:
                continue
            jitter = float(j.get("randomized_delay_s") or 0)
            wins.append(Window(j["unit"], st, st + timedelta(seconds=jitter + dur), fp,
                               kind="scheduled", jitter_s=jitter, description=j.get("description") or "",
                               klass=job_class(j["unit"], ann)))
    wins.sort(key=lambda w: (w.kind != "running", w.start))
    return wins


# ------------------------------------------------------------ box capacity

def capacity(hw: Optional[dict]) -> dict:
    """Total + currently-used resources, with tracked running jobs separated
    out so the forecast doesn't double count them."""
    hw = hw or {}
    running = _running_windows(_now(), load_annotations())
    run_vram = sum(w.footprint.vram_gb for w in running)
    run_ram = sum(w.footprint.ram_gb for w in running)
    return {
        "vram_total_gb": hw.get("gpu_mem_total_gb"),
        "vram_used_gb": hw.get("gpu_mem_used_gb"),
        "vram_baseline_gb": max(0.0, (hw.get("gpu_mem_used_gb") or 0) - run_vram) if hw.get("gpu_mem_total_gb") else None,
        "ram_total_gb": hw.get("ram_total_gb"),
        "ram_used_gb": hw.get("ram_used_gb"),
        "ram_baseline_gb": max(0.0, (hw.get("ram_used_gb") or 0) - run_ram),
        "cores_total": _cpu_count(),
        "cpu_pct": hw.get("cpu_percent"),
        "gpu_util_pct": hw.get("gpu_util_pct"),
    }


# ------------------------------------------------------------ window search

@dataclass
class Need:
    gpu_gb: float = 0.0
    ram_gb: float = 0.0
    cores: float = 0.0
    hours: float = 1.0


def _overlap_peak(wins: list[Window], start: datetime, end: datetime) -> tuple[dict, list[Window]]:
    """Peak simultaneous footprint of `wins` inside [start, end] (sweep over
    window edges), and which windows overlap at all."""
    ov = [w for w in wins if w.start < end and w.end > start]
    edges = sorted({start} | {w.start for w in ov if start <= w.start <= end})
    peak = {"vram_gb": 0.0, "ram_gb": 0.0, "cores": 0.0}
    for t in edges:
        live = [w for w in ov if w.start <= t < w.end]
        for k, attr in (("vram_gb", "vram_gb"), ("ram_gb", "ram_gb"), ("cores", "cores")):
            peak[k] = max(peak[k], sum(getattr(w.footprint, attr) for w in live))
    return peak, ov


def fits(need: Need, peak: dict, cap: dict) -> tuple[bool, list[str]]:
    why = []
    vt, vb = cap.get("vram_total_gb"), cap.get("vram_baseline_gb") or 0.0
    if need.gpu_gb and vt:
        if vb + peak["vram_gb"] + need.gpu_gb > vt - VRAM_MARGIN_GB:
            why.append(f"VRAM {vb + peak['vram_gb'] + need.gpu_gb:.1f} > {vt - VRAM_MARGIN_GB:.1f} GB usable")
    rt, rb = cap.get("ram_total_gb"), cap.get("ram_baseline_gb") or 0.0
    if need.ram_gb and rt:
        if rb + peak["ram_gb"] + need.ram_gb > rt - RAM_MARGIN_GB:
            why.append(f"RAM {rb + peak['ram_gb'] + need.ram_gb:.0f} > {rt - RAM_MARGIN_GB:.0f} GB usable")
    ct = cap.get("cores_total") or _cpu_count()
    if need.cores and peak["cores"] + need.cores > 0.9 * ct:
        why.append(f"CPU {peak['cores'] + need.cores:.0f} > {0.9 * ct:.0f} cores")
    return (not why), why


def find_window(need: Need, hw: Optional[dict] = None, horizon_h: float = 48.0,
                now: Optional[datetime] = None, wins: Optional[list[Window]] = None,
                cap: Optional[dict] = None) -> dict:
    """Earliest start in [now, now+horizon] where `need` fits for `need.hours`
    alongside the forecast. Also reports what happens if you start now."""
    now = now or _now()
    wins = forecast(horizon_h + need.hours, now=now) if wins is None else wins
    cap = cap or capacity(hw)
    span = timedelta(hours=need.hours)

    def evaluate(start: datetime) -> dict:
        peak, ov = _overlap_peak(wins, start, start + span)
        ok, why = fits(need, peak, cap)
        return {"start": start, "end": start + span, "fits": ok, "why": why,
                "overlaps": ov, "peak": peak}

    now_eval = evaluate(now)
    candidates = sorted({now} | {w.end for w in wins if now < w.end <= now + timedelta(hours=horizon_h)})
    best = None
    for c in candidates:
        e = evaluate(c)
        if e["fits"]:
            best = e
            break
    # Least-bad fallback: the candidate with the smallest VRAM/RAM excess.
    fallback = None
    if best is None and candidates:
        fallback = min((evaluate(c) for c in candidates),
                       key=lambda e: (len(e["why"]), e["peak"]["vram_gb"] + e["peak"]["ram_gb"] / 8))

    def pack(e: Optional[dict]) -> Optional[dict]:
        if not e:
            return None
        return {"start": _iso(e["start"]), "end": _iso(e["end"]), "fits": e["fits"], "why": e["why"],
                "starts_in_min": max(0, int((e["start"] - now).total_seconds() // 60)),
                "shares_box_with": [w.as_dict() for w in e["overlaps"] if is_heavy(w.footprint)],
                "context": [w.unit for w in e["overlaps"] if not is_heavy(w.footprint)],
                "peak_overlap": e["peak"]}

    return {"need": asdict(need), "now": _iso(now), "capacity": cap,
            "if_started_now": pack(now_eval), "earliest_fit": pack(best), "least_bad": pack(fallback)}


def quiet_until(kind: str = "gpu", now: Optional[datetime] = None, wins: Optional[list[Window]] = None,
                horizon_h: float = 48.0) -> Optional[datetime]:
    """When does the next `kind`-class window start (or None if nothing in
    the horizon)? kind='gpu' looks at GPU jobs; 'any' at all non-light."""
    now = now or _now()
    wins = forecast(horizon_h, now=now) if wins is None else wins
    starts = [w.start for w in wins
              if w.kind != "running" and w.start > now and (kind == "any" or "gpu" in w.footprint.klass)]
    return min(starts) if starts else None


# ------------------------------------------------------------------ health

def health(min_streak: int = 2) -> list[dict]:
    """Jobs whose most recent runs failed consecutively, plus jobs that are
    overdue (timer says they last ran, but no run row for > 2 periods)."""
    ann = load_annotations()
    out = []
    for j in inventory(tracked_only=True):
        if j.get("ignored") or j["scope"] == "cron":
            continue
        p = profile(j["unit"], ann)
        if p["fail_streak"] >= min_streak:
            out.append({"unit": j["unit"], "issue": f"failed {p['fail_streak']}× in a row",
                        "last_run": p["last_run"], "fail_streak": p["fail_streak"]})
    return out


# ------------------------------------------------------------------- brief

def _fmt_hm(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%H:%M")


def _fmt_fp(fp: Footprint) -> str:
    bits = []
    if fp.vram_gb >= 0.5:
        bits.append(f"VRAM ~{fp.vram_gb:.1f}G")
    if fp.ram_gb >= 2:
        bits.append(f"RAM ~{fp.ram_gb:.0f}G")
    if fp.cores >= 1:
        bits.append(f"{fp.cores:.0f} cores")
    if fp.gpu_util >= GPU_UTIL_PCT:
        bits.append(f"GPU {fp.gpu_util:.0f}%")
    if not bits:
        bits.append(fp.klass)
    if fp.source != "history":
        bits.append(fp.source)
    return ", ".join(bits)


def brief(hw: Optional[dict] = None, hours: float = 12.0, max_lines: int = 6) -> str:
    """Compact box-schedule notice for session start (pure sqlite reads,
    plus one systemctl call for running units — well under 100 ms)."""
    now = _now()
    wins = forecast(hours, now=now)
    cap = capacity(hw)
    lines = []
    parts = []
    if cap.get("vram_total_gb"):
        parts.append(f"VRAM {cap['vram_used_gb']:.1f}/{cap['vram_total_gb']:.0f}G")
    if cap.get("ram_total_gb"):
        parts.append(f"RAM {cap['ram_used_gb']:.0f}/{cap['ram_total_gb']:.0f}G")
    if cap.get("cpu_pct") is not None:
        parts.append(f"CPU {cap['cpu_pct']:.0f}%")
    running = [w for w in wins if w.kind == "running"]
    run_s = "; ".join(f"{w.unit} since {_fmt_hm(w.start)} (~{_fmt_fp(w.footprint)}, ends ~{_fmt_hm(w.end)})"
                      for w in running) or "nothing tracked"
    lines.append(f"now: {' · '.join(parts)} · running: {run_s}")
    heavy = [w for w in wins if w.kind == "scheduled" and is_heavy(w.footprint)]
    ctx = [w for w in wins if w.kind == "scheduled" and not is_heavy(w.footprint)]
    sched = sorted(heavy[:6] + ctx[:max(0, 3 - len(heavy))], key=lambda w: w.start)
    if sched:
        items = [f"{w.unit.removesuffix('.service')} {_fmt_hm(w.start)}–{_fmt_hm(w.end)} UTC ({_fmt_fp(w.footprint)})"
                 for w in sched]
        lines.append(f"next {hours:.0f}h: " + " · ".join(items))
    else:
        lines.append(f"next {hours:.0f}h: no heavy scheduled jobs")
    q = quiet_until("gpu", now=now, wins=wins)
    if q:
        h = (q - now).total_seconds() / 3600
        lines.append(f"GPU quiet until {_fmt_hm(q)} UTC ({h:.1f}h). Longer GPU run? "
                     "`claude-coordinator-jobs window --gpu-gb N --hours H`")
    else:
        lines.append("GPU: no scheduled GPU job in the next 48h")
    bad = health()
    if bad:
        lines.append("unhealthy: " + "; ".join(f"{b['unit']} {b['issue']}" for b in bad[:3]))
    return "\n".join(lines[:max_lines])


# ---------------------------------------------------------------- launcher

def launch(name: str, command: list[str], need: Need, nice: int = 10, log: Optional[str] = None,
           cwd: Optional[str] = None, description: str = "", gate_cmd: Optional[list[str]] = None,
           klass: str = "agent") -> dict:
    """Run `command` inside a transient user unit so it is cgroup-attributed
    and visible to every other session as a running job. With `log`, runs
    detached and returns immediately; otherwise blocks (stdio piped)."""
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-") or "run"
    unit = f"{ADHOC_PREFIX}{slug}-{_now().strftime('%m%d%H%M')}"
    cwd = cwd or os.getcwd()
    with connect() as c:
        # Keyed by the full unit name so _running_windows can join on it.
        c.execute(
            "INSERT OR REPLACE INTO job_declared(unit, name, gpu_gb, ram_gb, cores, hours, declared_at, cwd, command)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{unit}.service", slug, need.gpu_gb, need.ram_gb, need.cores, need.hours, _iso(_now()), cwd, shlex.join(command)))
        c.execute("DELETE FROM job_declared WHERE declared_at < datetime('now', '-30 days')")
    cmd = ["systemd-run", "--user", f"--unit={unit}", "--collect", "--same-dir",
           f"--description={description or slug}", f"-p", f"Nice={nice}",
           "-p", "CPUAccounting=yes", "-p", "MemoryAccounting=yes",
           "-p", f"OnFailure={FAILED_TEMPLATE}@{unit}.service"]
    for k in ("PATH", "HOME", "VIRTUAL_ENV", "CUDA_VISIBLE_DEVICES", "HF_HOME", "UV_CACHE_DIR"):
        if os.environ.get(k):
            cmd += [f"--setenv={k}={os.environ[k]}"]
    if log:
        lp = str(Path(log).expanduser().resolve())
        cmd += ["-p", f"StandardOutput=append:{lp}", "-p", f"StandardError=append:{lp}"]
    else:
        cmd += ["--wait", "--pipe"]
    if gate_cmd:
        # Queue behind production work via the same gate the timers use.
        command = gate_cmd + ["--unit", f"{unit}.service", "--class", klass,
                              "--gpu-gb", str(need.gpu_gb), "--ram-gb", str(need.ram_gb),
                              "--cores", str(need.cores), "--hours", str(need.hours), "--"] + command
    cmd += ["--"] + command
    rc = subprocess.call(cmd, cwd=cwd)
    return {"unit": unit, "rc": rc, "detached": bool(log), "log": log,
            "follow": f"journalctl --user -u {unit} -f" if not log else f"tail -f {log}",
            "stop": f"systemctl --user stop {unit}"}


# ------------------------------------------------------------- poller tick

def tick(hw: Optional[dict] = None) -> None:
    """Called by the hardware poller each 30s. Cheap; failures never
    propagate into the hardware sample path."""
    try:
        sync_inventory()
    except Exception:
        pass
    try:
        sample_running(hw)
    except Exception:
        pass
    try:
        last = _parse_iso(get_meta("jobs.journal_at"))
        if last is None or (_now() - last) > timedelta(minutes=10):
            backfill_from_journal()
    except Exception:
        pass
    try:
        last = _parse_iso(get_meta("jobs.health_at"))
        if last is None or (_now() - last) > timedelta(hours=6):
            notify_health()
            set_meta("jobs.health_at", _iso(_now()))
    except Exception:
        pass


# ------------------------------------------------------------------- gate
#
# Capacity-aware admission for heavy jobs. Systemd stays the scheduler; the
# gate wraps a unit's ExecStart (via a generated drop-in) or an ad-hoc `run`,
# and only decides *when* the command starts. Decisions are recorded so the
# layer's liveness is measurable (the deleted 2026-08 admission layer never
# fired and nobody could tell).

FAILED_TEMPLATE = "claude-job-failed"
DROPIN_NAME = "50-claude-jobs.conf"
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"


def gate_state() -> dict[str, dict]:
    with connect() as c:
        return {r["unit"]: dict(r) for r in c.execute("SELECT * FROM job_gate")}


def _gate_write(unit: str, **fields) -> None:
    fields["updated_at"] = _iso(_now())
    with connect() as c:
        cur = c.execute("SELECT unit FROM job_gate WHERE unit = ?", (unit,)).fetchone()
        if cur:
            sets = ", ".join(f"{k} = ?" for k in fields)
            c.execute(f"UPDATE job_gate SET {sets} WHERE unit = ?", (*fields.values(), unit))
        else:
            cols = ["unit", *fields]
            c.execute(f"INSERT INTO job_gate({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      (unit, *fields.values()))


def _gate_clear(unit: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM job_gate WHERE unit = ?", (unit,))


def _gate_event(unit: str, klass: str, decision: str, waited_s: float = 0.0, reason: str = "") -> None:
    with connect() as c:
        c.execute("INSERT INTO gate_events(timestamp, unit, class, decision, waited_s, reason) VALUES (?,?,?,?,?,?)",
                  (_iso(_now()), unit, klass, decision, waited_s, reason[:300]))


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _expire_gate_rows() -> None:
    """Drop gate rows whose gate process is gone (crash, SIGKILL, reboot)."""
    for unit, g in gate_state().items():
        if not _pid_alive(g.get("pid")):
            _gate_clear(unit)
            _gate_event(unit, g.get("class", "?"), "expired", reason="gate process gone")


def gate_decision(need: Need, klass: str, now: datetime, wins: list[Window], cap: dict,
                  ignore_reservations: bool = False) -> tuple[bool, list[str], list[Window]]:
    """Can a job of `klass` with envelope `need` start now?

    - Running jobs (leases + observed) always count.
    - Scheduled jobs of a strictly HIGHER class that start inside this job's
      expected span are reserved: we must fit alongside them too. Same or
      lower class is first-come: they will queue behind us if needed.
    Returns (fits, reasons, blocking windows)."""
    span_end = now + timedelta(hours=need.hours)
    rank = CLASS_RANK.get(klass, 1)
    relevant = []
    for w in wins:
        if w.kind == "running":
            relevant.append(w)
        elif not ignore_reservations and CLASS_RANK.get(w.klass, 1) > rank and w.start < span_end and w.end > now:
            relevant.append(w)
    peak, ov = _overlap_peak(relevant, now, span_end)
    ok, why = fits(need, peak, cap)
    return ok, why, ov


def gate(unit: str, command: list[str], need: Need, klass: str = "batch",
         max_wait_h: Optional[float] = None, on_timeout: str = "run",
         dry_run: bool = False, poll_s: float = GATE_POLL_S, log=print) -> int:
    """Wait for capacity, take a lease, run `command`, release. Returns the
    command's exit code (or 0 for a skip / dry-run, 2 for a bad request)."""
    from .readers import latest_hardware_sample
    klass = klass if klass in CLASS_RANK else "batch"
    max_wait = timedelta(hours=max_wait_h if max_wait_h is not None else DEFAULT_MAX_WAIT_H[klass])
    t0 = _now()
    _gate_write(unit, state="waiting", **{"class": klass}, gpu_gb=need.gpu_gb, ram_gb=need.ram_gb,
                cores=need.cores, hours=need.hours, requested_at=_iso(t0), pid=os.getpid(), reason="")
    last_reason = ""
    try:
        while True:
            now = _now()
            hw = latest_hardware_sample()
            wins = [w for w in forecast(need.hours + 1, now=now) if w.unit != unit]
            cap = capacity(hw)
            waited = (now - t0).total_seconds()
            aged = waited > max_wait.total_seconds() / 2   # aging: after half the budget, ignore reservations
            ok, why, blockers = gate_decision(need, klass, now, wins, cap, ignore_reservations=aged)
            if ok:
                if dry_run:
                    _gate_event(unit, klass, "dry-run", waited, "would start now")
                    log(f"[gate] {unit}: fits now (class {klass}, GPU {need.gpu_gb:g}G RAM {need.ram_gb:g}G) — dry run")
                    return 0
                if waited > 0.5 * poll_s:
                    _gate_event(unit, klass, "wait", waited, last_reason)
                else:
                    _gate_event(unit, klass, "pass", 0.0, "")
                break
            reason = "; ".join(why) + " | blocked by " + ", ".join(
                f"{w.unit}[{w.kind}]" for w in blockers if is_heavy(w.footprint))
            if dry_run:
                _gate_event(unit, klass, "dry-run", 0.0, "would wait: " + reason)
                log(f"[gate] {unit}: would WAIT — {reason}")
                return 0
            if waited >= max_wait.total_seconds():
                if on_timeout == "skip":
                    _gate_event(unit, klass, "timeout-skip", waited, reason)
                    log(f"[gate] {unit}: waited {waited / 3600:.1f}h, still blocked — SKIPPING ({reason})")
                    notify(f"job skipped: {unit}", f"waited {waited / 3600:.1f}h for capacity; {reason[:160]}")
                    return 0
                _gate_event(unit, klass, "timeout-run", waited, reason)
                log(f"[gate] {unit}: waited {waited / 3600:.1f}h, still blocked — running anyway ({reason})")
                notify(f"job running blocked: {unit}", f"waited {waited / 3600:.1f}h; starting into contention. {reason[:140]}")
                break
            if reason != last_reason or int(waited) % 600 < poll_s:
                log(f"[gate] {unit}: waiting ({waited / 60:.0f} min) — {reason}")
            last_reason = reason
            _gate_write(unit, reason=reason[:300])
            import time as _t
            _t.sleep(poll_s)

        started = _now()
        _gate_write(unit, state="running", started_at=_iso(started),
                    expected_end=_iso(started + timedelta(hours=need.hours)), reason="")
        import signal
        proc = subprocess.Popen(command)

        def _forward(signum, _frame):
            try:
                proc.send_signal(signum)
            except ProcessLookupError:
                pass
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, _forward)
        return proc.wait()
    finally:
        _gate_clear(unit)


# ---------------------------------------------------------- notifications

def _load_dotenv() -> dict:
    env = {}
    p = Path.home() / ".claude" / ".env"
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def notify(title: str, body: str) -> bool:
    """Best-effort push via ntfy. Topic from NTFY_TOPIC (env or ~/.claude/.env),
    server from NTFY_URL (default https://ntfy.sh). Silent no-op if unset."""
    env = {**_load_dotenv(), **os.environ}
    topic = env.get("NTFY_TOPIC")
    if not topic:
        return False
    url = env.get("NTFY_URL", "https://ntfy.sh").rstrip("/") + "/" + topic
    try:
        import urllib.request
        req = urllib.request.Request(url, data=body.encode(), headers={"Title": title[:120]}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception:
        return False


def notify_health(min_streak: int = 2) -> list[dict]:
    """Push one notification per failing job per day (poller calls this
    every 6h). Returns what was sent."""
    sent = []
    today = _now().strftime("%Y-%m-%d")
    for b in health(min_streak=min_streak):
        key = f"jobs.notified:{b['unit']}"
        if get_meta(key) == today:
            continue
        if notify(f"job failing: {b['unit']}", f"{b['issue']} (last {b['last_run']}). journalctl --user -u {b['unit']}"):
            set_meta(key, today)
            sent.append(b)
    return sent


# ------------------------------------------------------- drop-in installer

def _unit_exec_start(unit: str) -> list[str]:
    """Raw ExecStart= lines from the unit's own fragment (not drop-ins)."""
    out = _run(["systemctl", "--user", "show", "-p", "FragmentPath", "--value", unit])
    path = Path(out.strip())
    lines = []
    try:
        for line in path.read_text().splitlines():
            if line.startswith("ExecStart="):
                lines.append(line[len("ExecStart="):])
    except OSError:
        pass
    return lines


def render_dropin(unit: str, a: dict, gate_bin: str) -> Optional[str]:
    """Drop-in text for a unit from its jobs.yaml annotation, or None."""
    execs = _unit_exec_start(unit)
    if len(execs) != 1:
        return None  # multi-ExecStart or unreadable: leave alone
    klass = a.get("class", "batch")
    exp = a.get("expect") or {}
    args = [gate_bin, "gate", "--unit", "%n", "--class", klass]
    if exp.get("gpu_gb") is not None:
        args += ["--gpu-gb", str(exp["gpu_gb"])]
    if exp.get("ram_gb") is not None:
        args += ["--ram-gb", str(exp["ram_gb"])]
    if exp.get("cores") is not None:
        args += ["--cores", str(exp["cores"])]
    if exp.get("hours") is not None:
        args += ["--hours", str(exp["hours"])]
    if a.get("max_wait_h") is not None:
        args += ["--max-wait", str(a["max_wait_h"])]
    if a.get("on_timeout"):
        args += ["--on-timeout", a["on_timeout"]]
    unit_lines = [f"OnFailure={FAILED_TEMPLATE}@%n.service"]
    for dep in a.get("after") or []:
        unit_lines.append(f"After={dep}")
    svc_lines = []
    if a.get("gate", True):
        svc_lines += ["ExecStart=", "ExecStart=" + " ".join(args) + " -- " + execs[0]]
    if a.get("memory_max"):
        svc_lines.append(f"MemoryMax={a['memory_max']}")
    if a.get("nice") is not None:
        svc_lines.append(f"Nice={a['nice']}")
    if a.get("cpu_weight") is not None:
        svc_lines.append(f"CPUWeight={a['cpu_weight']}")
    if a.get("io_weight") is not None:
        svc_lines.append(f"IOWeight={a['io_weight']}")
    body = ["# Generated by `claude-coordinator-jobs install-gates` from ~/.claude/jobs.yaml.",
            "# Do not edit; re-run the installer. `uninstall-gates` removes it.",
            "[Unit]", *unit_lines, "", "[Service]", *svc_lines, ""]
    return "\n".join(body)


def install_gates(gate_bin: Optional[str] = None, dry_run: bool = False) -> list[dict]:
    """Write (or refresh) drop-ins for every jobs.yaml unit with class/gate/
    limits set; remove drop-ins for units no longer annotated; daemon-reload."""
    gate_bin = gate_bin or str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "claude-coordinator-jobs")
    ann = load_annotations()
    results = []
    wanted = {}
    for unit, a in ann.items():
        a = a or {}
        if unit.startswith("cron:") or not any(k in a for k in ("class", "gate", "memory_max", "after", "nice")):
            continue
        text = render_dropin(unit, a, gate_bin)
        if text is None:
            results.append({"unit": unit, "action": "skip", "why": "ExecStart not single-line / unit unreadable"})
            continue
        wanted[unit] = text
    for d in USER_UNIT_DIR.glob(f"*.service.d/{DROPIN_NAME}"):
        unit = d.parent.name.removesuffix(".d")
        if unit not in wanted:
            results.append({"unit": unit, "action": "remove"})
            if not dry_run:
                d.unlink()
    for unit, text in wanted.items():
        path = USER_UNIT_DIR / f"{unit}.d" / DROPIN_NAME
        cur = path.read_text() if path.exists() else None
        action = "unchanged" if cur == text else ("update" if cur else "create")
        results.append({"unit": unit, "action": action, "path": str(path)})
        if not dry_run and action != "unchanged":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if not dry_run:
        _run(["systemctl", "--user", "daemon-reload"], timeout=20)
    return results


def uninstall_gates() -> int:
    n = 0
    for d in USER_UNIT_DIR.glob(f"*.service.d/{DROPIN_NAME}"):
        d.unlink(); n += 1
        try:
            d.parent.rmdir()
        except OSError:
            pass
    _run(["systemctl", "--user", "daemon-reload"], timeout=20)
    return n
