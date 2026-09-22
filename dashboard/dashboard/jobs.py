"""Job-ledger reader for the dashboard /jobs page. Thin, cached wrapper
over coordinator.jobs so page renders never shell out more than once per
TTL window."""
from __future__ import annotations

from datetime import timedelta

from coordinator import jobs
from coordinator.readers import latest_hardware_sample

from .cache import ttl_cache


@ttl_cache(seconds=15)
def page_data(hours: float = 24.0) -> dict:
    now = jobs._now()
    hw = latest_hardware_sample()
    wins = jobs.forecast(hours, now=now)
    horizon = timedelta(hours=hours)

    def pct(dt) -> float:
        return max(0.0, min(100.0, 100.0 * (dt - now).total_seconds() / horizon.total_seconds()))

    lanes: dict[str, list[dict]] = {}
    for w in wins:
        left = pct(w.start)
        right = pct(w.end)
        lanes.setdefault(w.unit, []).append({
            "left": left, "width": max(0.6, right - left),
            "kind": w.kind, "klass": w.footprint.klass,
            "label": f"{w.start.strftime('%a %H:%M')}–{w.end.strftime('%H:%M')} · {jobs._fmt_fp(w.footprint)}",
        })
    ticks = []
    step = 3 if hours <= 36 else 12
    t = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while t < now + horizon:
        if t.hour % step == 0:
            ticks.append({"left": pct(t), "label": t.strftime("%H:%M") if t.hour else t.strftime("%a")})
        t += timedelta(hours=1)

    inv = jobs.inventory_with_profiles()
    with jobs.connect() as c:
        recent = [dict(r) for r in c.execute(
            "SELECT unit, started_at, finished_at, duration_s, result, cpu_seconds, peak_rss_gb, peak_vram_gb, "
            "est_ram_gb, est_vram_gb, avg_gpu_util, source FROM job_runs ORDER BY started_at DESC LIMIT 40")]
    q = jobs.quiet_until("gpu", now=now, wins=wins)
    with jobs.connect() as c:
        gate_events = [dict(r) for r in c.execute("SELECT * FROM gate_events ORDER BY id DESC LIMIT 20")]
    return {
        "gate": jobs.gate_state(),
        "gate_events": gate_events,
        "now": now, "hours": hours, "ticks": ticks,
        "lanes": [{"unit": u, "bars": b} for u, b in lanes.items()],
        "running": [w.as_dict() | {"fp_text": jobs._fmt_fp(w.footprint)} for w in wins if w.kind == "running"],
        "inventory": [r | {"fp_text": jobs._fmt_fp(jobs.Footprint(**r["footprint"]))} for r in inv],
        "recent": recent,
        "health": jobs.health(),
        "capacity": jobs.capacity(hw),
        "gpu_quiet_until": q,
        "gpu_procs": jobs._gpu_procs(),
    }
