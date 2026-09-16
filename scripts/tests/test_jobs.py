"""Unit tests for the pure parts of coordinator.jobs (no systemd, no DB).

Run:  ~/claude-system/coordinator/.venv/bin/python -m pytest scripts/tests -q
  or: ~/claude-system/coordinator/.venv/bin/python scripts/tests/test_jobs.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "coordinator"))

from coordinator import jobs  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 9, 16, 22, 0, tzinfo=UTC)


def _win(unit, start_h, dur_h, vram=0.0, ram=0.0, cores=0.0, kind="scheduled"):
    fp = jobs.Footprint(vram_gb=vram, ram_gb=ram, cores=cores, duration_s=dur_h * 3600)
    fp.klass = jobs.classify(fp)
    return jobs.Window(unit, T0 + timedelta(hours=start_h), T0 + timedelta(hours=start_h + dur_h), fp, kind=kind)


CAP = {"vram_total_gb": 16.0, "vram_baseline_gb": 0.7, "ram_total_gb": 91.0, "ram_baseline_gb": 10.0, "cores_total": 32}


def test_parse_span():
    assert jobs._parse_span("10min") == 600
    assert jobs._parse_span("1h 30min") == 5400
    assert jobs._parse_span("0") == 0
    assert jobs._parse_span("2d") == 172800
    assert jobs._parse_span("[not set]") == 0


def test_parse_systemd_ts():
    dt = jobs._parse_systemd_ts("Wed 2026-09-16 07:20:17 UTC")
    assert dt == datetime(2026, 9, 16, 7, 20, 17, tzinfo=UTC)
    assert jobs._parse_systemd_ts("") is None
    assert jobs._parse_systemd_ts("n/a") is None


def test_classify():
    assert jobs.classify(jobs.Footprint(vram_gb=9.6, ram_gb=23, cores=1, duration_s=1800)) == "gpu+ram"
    assert jobs.classify(jobs.Footprint(duration_s=5)) == "light"
    assert jobs.classify(jobs.Footprint(duration_s=130)) == "light"          # 2 min, nothing heavy
    assert jobs.classify(jobs.Footprint(duration_s=7 * 3600, cores=1)) == "long-light"
    assert jobs.classify(jobs.Footprint(cores=8, duration_s=600)) == "cpu"
    assert jobs.classify(jobs.Footprint(cores=8, duration_s=30)) == "light"  # a burst


def test_p90_and_median():
    assert jobs._p90([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 9
    assert jobs._p90([5]) == 5
    assert jobs._p90([]) is None
    assert jobs._median([3, 1, 2]) == 2


def test_overlap_peak_sums_simultaneous_only():
    wins = [_win("a", 1, 1, vram=9.6), _win("b", 1.5, 1, vram=5.0), _win("c", 5, 1, vram=8.0)]
    peak, ov = jobs._overlap_peak(wins, T0, T0 + timedelta(hours=3))
    assert {w.unit for w in ov} == {"a", "b"}
    assert abs(peak["vram_gb"] - 14.6) < 1e-9  # a and b overlap 1.5–2.0
    peak2, _ = jobs._overlap_peak(wins, T0 + timedelta(hours=4.5), T0 + timedelta(hours=6))
    assert peak2["vram_gb"] == 8.0


def test_fits_margins():
    need = jobs.Need(gpu_gb=8, ram_gb=20, cores=4, hours=1)
    ok, why = jobs.fits(need, {"vram_gb": 0, "ram_gb": 0, "cores": 0}, CAP)
    assert ok and not why
    ok, why = jobs.fits(need, {"vram_gb": 9.6, "ram_gb": 0, "cores": 0}, CAP)
    assert not ok and why and why[0].startswith("VRAM")


def test_find_window_picks_end_of_conflict():
    # A 9.6 GB retrain 1h from now for 1h; we need 8 GB for 2h → must wait
    # until the retrain ends at +2h.
    wins = [_win("retrain", 1, 1, vram=9.6, ram=23)]
    res = jobs.find_window(jobs.Need(gpu_gb=8, ram_gb=10, hours=2), now=T0, wins=wins, cap=CAP)
    assert res["if_started_now"]["fits"] is False
    assert res["earliest_fit"]["start"] == jobs._iso(T0 + timedelta(hours=2))
    assert res["earliest_fit"]["starts_in_min"] == 120


def test_find_window_fits_now_when_short():
    wins = [_win("retrain", 1, 1, vram=9.6)]
    res = jobs.find_window(jobs.Need(gpu_gb=8, hours=0.5), now=T0, wins=wins, cap=CAP)
    assert res["if_started_now"]["fits"] is True
    assert res["earliest_fit"]["starts_in_min"] == 0


def test_find_window_running_job_counts():
    wins = [_win("big", -0.5, 3, vram=12.0, kind="running")]
    res = jobs.find_window(jobs.Need(gpu_gb=6, hours=1), now=T0, wins=wins, cap=CAP)
    assert not res["if_started_now"]["fits"]
    assert res["earliest_fit"]["start"] == jobs._iso(T0 + timedelta(hours=2.5))


def test_quiet_until_gpu_only():
    wins = [_win("cpu-job", 0.5, 1, cores=8), _win("gpu-job", 3, 1, vram=5), _win("now", -1, 5, vram=9, kind="running")]
    q = jobs.quiet_until("gpu", now=T0, wins=wins)
    assert q == T0 + timedelta(hours=3)
    assert jobs.quiet_until("gpu", now=T0, wins=[]) is None


def test_occurrences_monotonic_and_cron():
    job = {"scope": "user", "schedule": "every 30min", "interval_s": 1800,
           "next_run": jobs._iso(T0 + timedelta(minutes=10))}
    occ = jobs.occurrences(job, base=T0, days=1)
    assert occ[0] == T0 + timedelta(minutes=10)
    assert len(occ) == 48
    try:
        import croniter  # noqa: F401
    except ImportError:
        return
    cron = {"scope": "cron", "schedule": "0 3 * * *"}
    occ = jobs.occurrences(cron, base=T0, days=2)
    assert len(occ) == 2 and occ[0].hour == 3 and occ[0].minute == 0


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
