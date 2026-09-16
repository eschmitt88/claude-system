"""`claude-coordinator-jobs` — schedule-aware headroom CLI.

Subcommands (all accept --json):
  brief                 6-line box-schedule notice (what session-start injects)
  now                   running tracked jobs + who holds the GPU right now
  list                  inventory of recurring jobs with learned footprints
  runs [UNIT] [-n N]    recent observed runs
  profile UNIT          footprint + reliability for one job
  forecast [--hours H]  predicted busy windows (running + scheduled)
  window --gpu-gb G --ram-gb R --cores C --hours H [--horizon 48]
                        earliest slot where that envelope fits
  slot --hours H [...]  best recurring daily start time for a NEW scheduled job
  health                jobs failing repeatedly (exit 1 if any)
  sync [--backfill D]   refresh inventory; back-fill runs from the journal
  run --name N [--gpu-gb G --ram-gb R --cores C --hours H --log F --nice N] -- CMD...
                        launch CMD as a transient, cgroup-attributed user unit
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from . import jobs
from .readers import latest_hardware_sample


def _hm(s: str | None) -> str:
    dt = jobs._parse_iso(s)
    return dt.astimezone(timezone.utc).strftime("%a %H:%M") if dt else "—"


def _dur(s: float | None) -> str:
    if not s:
        return "—"
    s = int(s)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    return f"{s / 3600:.1f}h"


def _fp_line(fp: dict) -> str:
    return jobs._fmt_fp(jobs.Footprint(**fp))


def cmd_brief(a):
    print(jobs.brief(latest_hardware_sample(), hours=a.hours))


def cmd_now(a):
    running = jobs.sample_running(latest_hardware_sample()) if a.sample else []
    wins = [w for w in jobs.forecast(1) if w.kind == "running"]
    gpu = jobs._gpu_procs()
    if a.json:
        print(json.dumps({"running": [w.as_dict() for w in wins], "gpu_procs": gpu}, indent=2, default=str))
        return
    print("=== Running tracked jobs ===")
    if not wins:
        print("  none")
    for w in wins:
        print(f"  {w.unit}  since {_hm(jobs._iso(w.start))}  expected end ~{_hm(jobs._iso(w.end))}  ({_fp_line(w.footprint.as_dict())})")
    print("=== GPU memory holders ===")
    if not gpu:
        print("  none")
    for g in sorted(gpu, key=lambda g: -g["vram_mb"]):
        print(f"  {g['vram_mb']:7.0f} MB  pid {g['pid']:<7} {g.get('comm','')[:20]:<20} {g['unit'] or g['cgroup'] or '?'}")


def cmd_list(a):
    rows = jobs.inventory_with_profiles()
    if a.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(f"{'unit':44} {'scope':6} {'schedule':30} {'next':9} {'p90 dur':7} {'footprint':34} runs")
    for r in rows:
        fp = r["footprint"]
        flag = " ✗" + str(r["fail_streak"]) if r["fail_streak"] else ""
        print(f"{r['unit'][:44]:44} {r['scope']:6} {(r.get('schedule') or '')[:30]:30} "
              f"{_hm(r.get('next_run')) if r.get('next_run') else (_hm(r['next_runs'][0]) if r['next_runs'] else '—'):9} "
              f"{_dur(fp['duration_s']):7} {_fp_line(fp)[:34]:34} {r['n_runs']}{flag}")


def cmd_runs(a):
    q = "SELECT * FROM job_runs" + (" WHERE unit = ?" if a.unit else "") + " ORDER BY started_at DESC LIMIT ?"
    with jobs.connect() as c:
        rows = [dict(r) for r in c.execute(q, ((a.unit, a.n) if a.unit else (a.n,)))]
    if a.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(f"{'unit':40} {'started (UTC)':14} {'dur':6} {'result':7} {'cpu-s':7} {'rss':6} {'vram':6} {'Δram':6} {'gpu%':5} src")
    print("  (vram = per-unit NVML when tracked live, else box-level delta; Δram = box-level delta vs 10 min before)")
    for r in rows:
        est_ram = r["est_ram_gb"] if (r["est_ram_gb"] or 0) > 0 else 0.0
        print(f"{r['unit'][:40]:40} {_hm(r['started_at']):14} {_dur(r['duration_s']):6} {r['result']:7} "
              f"{(r['cpu_seconds'] or 0):7.0f} {(r['peak_rss_gb'] or 0):5.1f}G {(r['peak_vram_gb'] or r['est_vram_gb'] or 0):5.1f}G "
              f"{est_ram:5.1f}G {(r['avg_gpu_util'] or 0):4.0f} {r['source']}")


def cmd_profile(a):
    p = jobs.profile(a.unit)
    if a.json:
        print(json.dumps(p, indent=2, default=str))
        return
    fp = p["footprint"]
    print(f"{a.unit}: {fp['klass']}  (from {fp['n_runs']} successful runs, {p['n_failed']} failed, source={fp['source']})")
    print(f"  duration median {_dur(fp['duration_med_s'])}, p90 {_dur(fp['duration_s'])}; CPU {fp['cores']:.1f} cores avg "
          f"(median {p['cpu_seconds_med'] or 0:.0f} cpu-s)")
    print(f"  RAM p90 {fp['ram_gb']:.1f} GB; VRAM p90 {fp['vram_gb']:.1f} GB; GPU util median {fp['gpu_util']:.0f}%"
          + (f"  ({p['n_confounded']} run(s) overlapped another job and were excluded from RAM/VRAM)" if p.get('n_confounded') else ""))
    print(f"  last run {_hm(p['last_run'])} → {p['last_result']}; fail streak {p['fail_streak']}")
    if p.get("project") or p.get("notes"):
        print(f"  project={p.get('project')} notes={p.get('notes')}")


def cmd_forecast(a):
    wins = jobs.forecast(a.hours, include_light=a.all)
    if a.json:
        print(json.dumps([w.as_dict() for w in wins], indent=2, default=str))
        return
    now = jobs._now()
    print(f"=== Forecast next {a.hours:g}h (UTC; start±jitter, end = start + jitter + p90 duration) ===")
    if not wins:
        print("  nothing heavy scheduled")
    for w in wins:
        tag = {"running": "RUNNING ", "declared": "declared", "scheduled": "        "}[w.kind]
        j = f"+{int(w.jitter_s // 60)}m" if w.jitter_s else ""
        print(f"  {tag} {w.start.strftime('%a %H:%M')}{j:>4} → {w.end.strftime('%a %H:%M')}  {w.unit[:40]:40} {_fp_line(w.footprint.as_dict())}")
    q = jobs.quiet_until("gpu", now=now, wins=wins)
    print(f"  next GPU job starts: {q.strftime('%a %H:%M') if q else 'none in horizon'}")


def _need(a) -> jobs.Need:
    return jobs.Need(gpu_gb=a.gpu_gb, ram_gb=a.ram_gb, cores=a.cores, hours=a.hours)


def _print_window(res: dict):
    n = res["need"]
    cap = res["capacity"]
    print(f"need: GPU {n['gpu_gb']:g} GB, RAM {n['ram_gb']:g} GB, {n['cores']:g} cores, for {n['hours']:g}h")
    if cap.get("vram_total_gb"):
        print(f"box now: VRAM {cap['vram_used_gb']:.1f}/{cap['vram_total_gb']:.0f} GB (baseline {cap['vram_baseline_gb']:.1f}), "
              f"RAM {cap['ram_used_gb']:.0f}/{cap['ram_total_gb']:.0f} GB, {cap['cores_total']} cores")
    now = res["if_started_now"]
    if now["fits"]:
        shares = ", ".join(w["unit"] for w in now["shares_box_with"]) or "nobody"
        print(f"start now: FITS (shares the box with: {shares})")
    else:
        print(f"start now: CONFLICT — {'; '.join(now['why'])}")
        for w in now["shares_box_with"]:
            print(f"    {w['unit']} {_hm(w['start'])}→{_hm(w['end'])} ({_fp_line(w['footprint'])})")
    e = res["earliest_fit"]
    if e and e["starts_in_min"] > 0:
        print(f"earliest fit: {_hm(e['start'])} UTC (in {e['starts_in_min'] // 60}h {e['starts_in_min'] % 60}m) → {_hm(e['end'])}")
    elif not e:
        lb = res["least_bad"]
        print("no clean window in horizon" + (f"; least bad: {_hm(lb['start'])} ({'; '.join(lb['why'])})" if lb else ""))


def cmd_window(a):
    res = jobs.find_window(_need(a), latest_hardware_sample(), horizon_h=a.horizon)
    if a.json:
        print(json.dumps(res, indent=2, default=str))
        return
    _print_window(res)


def cmd_slot(a):
    """Best recurring daily start (UTC, 30-min grid) for a new job of the
    given envelope, judged against the 7-day forecast."""
    now = jobs._now()
    hw = latest_hardware_sample()
    wins = jobs.forecast(7 * 24, now=now)
    cap = jobs.capacity(hw)
    need = _need(a)
    results = []
    for half in range(48):
        conflicts = 0
        worst = 0.0
        for day in range(1, 7):
            start = (now + timedelta(days=day)).replace(hour=half // 2, minute=30 * (half % 2), second=0, microsecond=0)
            peak, _ = jobs._overlap_peak(wins, start, start + timedelta(hours=need.hours))
            ok, _why = jobs.fits(need, peak, cap)
            conflicts += 0 if ok else 1
            worst = max(worst, peak["vram_gb"] + peak["ram_gb"] / 8 + peak["cores"] / 4)
        results.append({"start_utc": f"{half // 2:02d}:{30 * (half % 2):02d}", "conflict_days": conflicts, "load": round(worst, 2)})
    results.sort(key=lambda r: (r["conflict_days"], r["load"], r["start_utc"]))
    if a.json:
        print(json.dumps(results[:10], indent=2))
        return
    print("best recurring daily slots (UTC) for that envelope, next 6 days:")
    for r in results[:8]:
        print(f"  {r['start_utc']}  conflicts on {r['conflict_days']}/6 days, overlap load {r['load']}")


def cmd_health(a):
    bad = jobs.health()
    if a.json:
        print(json.dumps(bad, indent=2))
    elif not bad:
        print("all scheduled jobs healthy")
    else:
        for b in bad:
            print(f"  {b['unit']}: {b['issue']} (last {_hm(b['last_run'])})")
    sys.exit(1 if bad else 0)


def cmd_sync(a):
    n = jobs.sync_inventory(force_occurrences=True)
    print(f"inventory: {n} jobs")
    if a.backfill:
        t = jobs.backfill_from_journal(days=a.backfill)
        print(f"journal back-fill ({a.backfill}d): {t} runs")
    running = jobs.sample_running(latest_hardware_sample())
    print(f"running now: {len(running)}")


def cmd_run(a):
    argv = list(a.argv or [])
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("run: missing command after --", file=sys.stderr)
        sys.exit(2)
    need = _need(a)
    if need.gpu_gb or need.ram_gb or need.cores:
        res = jobs.find_window(need, latest_hardware_sample(), horizon_h=24)
        n = res["if_started_now"]
        if not n["fits"]:
            print(f"[jobs] note: starting now conflicts with the forecast — {'; '.join(n['why'])}", file=sys.stderr)
            e = res["earliest_fit"]
            if e:
                print(f"[jobs] earliest clean window: {_hm(e['start'])} UTC. Proceeding anyway (advisory).", file=sys.stderr)
    out = jobs.launch(a.name, argv, need, nice=a.nice, log=a.log, description=a.description or "")
    if a.json:
        print(json.dumps(out))
    elif out["detached"]:
        print(f"[jobs] launched {out['unit']} (detached). follow: {out['follow']}   stop: {out['stop']}")
    sys.exit(out["rc"] if not out["detached"] else 0)


def main() -> int:
    p = argparse.ArgumentParser(prog="claude-coordinator-jobs", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("brief"); s.add_argument("--hours", type=float, default=12); s.set_defaults(fn=cmd_brief)
    s = sub.add_parser("now"); s.add_argument("--no-sample", dest="sample", action="store_false"); s.set_defaults(fn=cmd_now)
    s = sub.add_parser("list"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("runs"); s.add_argument("unit", nargs="?"); s.add_argument("-n", type=int, default=20); s.set_defaults(fn=cmd_runs)
    s = sub.add_parser("profile"); s.add_argument("unit"); s.set_defaults(fn=cmd_profile)
    s = sub.add_parser("forecast"); s.add_argument("--hours", type=float, default=24); s.add_argument("--all", action="store_true"); s.set_defaults(fn=cmd_forecast)

    def need_args(sp):
        sp.add_argument("--gpu-gb", type=float, default=0.0)
        sp.add_argument("--ram-gb", type=float, default=0.0)
        sp.add_argument("--cores", type=float, default=0.0)
        sp.add_argument("--hours", type=float, default=1.0)

    s = sub.add_parser("window"); need_args(s); s.add_argument("--horizon", type=float, default=48); s.set_defaults(fn=cmd_window)
    s = sub.add_parser("slot"); need_args(s); s.set_defaults(fn=cmd_slot)
    s = sub.add_parser("health"); s.set_defaults(fn=cmd_health)
    s = sub.add_parser("sync"); s.add_argument("--backfill", type=float, default=0); s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("run"); need_args(s)
    s.add_argument("--name", required=True); s.add_argument("--log"); s.add_argument("--nice", type=int, default=10)
    s.add_argument("--description", default="")
    s.add_argument("argv", nargs=argparse.REMAINDER, help="command to run (after --)")
    s.set_defaults(fn=cmd_run)

    a = p.parse_args()
    a.fn(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
