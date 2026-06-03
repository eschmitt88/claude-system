"""`claude-coordinator-status` CLI. Fast summary for /headroom skill.

Prints:
- Claude token usage over the trailing 5h and 7d windows (state.db totals).
- Latest hardware sample with per-resource units.
- Running + queued jobs (top 10 each) with ETA if available.
- Last 5 completed jobs with est-vs-actual token delta.

Pure read path — no writes, no policy. Should return in <1s.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import agency, ccusage, config
from .readers import (
    latest_hardware_sample,
    queued_jobs,
    recent_completed_jobs,
    tokens_in_last,
)


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _fmt_gb(v):
    return f"{v:.1f} GB" if v is not None else "n/a"


def _fmt_pct(v):
    return f"{v:.0f}%" if v is not None else "n/a"


def _fmt_usd(v):
    return f"${v:.2f}" if v is not None else "n/a"


def render(as_json: bool = False) -> str:
    # ccusage calls are the slowest part (~0.4s each) — run them concurrently.
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_block = ex.submit(ccusage.active_block)
        f_7d = ex.submit(ccusage.weekly_anchored)
        five_h = tokens_in_last(5 * 3600)
        seven_d = tokens_in_last(7 * 24 * 3600)
        hw = latest_hardware_sample()
        queued = queued_jobs(limit=10)
        completed = recent_completed_jobs(limit=5)
        cc_block = f_block.result()
        cc_7d = f_7d.result()

    # Agency verdict reuses the values we just fetched (no extra ccusage calls).
    agency_verdict = agency.verdict(weekly=cc_7d, block=cc_block, hw=hw or {})

    if as_json:
        return json.dumps(
            {
                "tokens_5h": five_h,
                "tokens_7d": seven_d,
                "ccusage_active_block": cc_block,
                "ccusage_weekly": cc_7d,
                "agency": agency_verdict,
                "hardware": hw,
                "running_and_queued": queued,
                "recent_completed": completed,
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
            default=str,
        )

    out = []
    if cc_block or cc_7d:
        out.append("=== Claude quota (via ccusage — reads ~/.claude/projects/*.jsonl) ===")
        if cc_block:
            pct = cc_block.get("pct_vs_max20x_limit")
            pct_str = f" ({pct:.1f}% of Max-20x est.)" if pct is not None else ""
            rem = cc_block.get("remaining_minutes")
            rem_str = f"~{rem // 60}h {rem % 60}m left" if rem is not None else "active"
            out.append(
                f"  5h block: {_fmt_tokens(cc_block['tokens'])} tokens  "
                f"{_fmt_usd(cc_block.get('cost_usd'))}{pct_str} — {rem_str}"
            )
            burn = cc_block.get("burn_tokens_per_min")
            proj = cc_block.get("projection_tokens")
            proj_pct = None
            if proj and cc_block.get("max20x_limit_tokens"):
                proj_pct = 100.0 * proj / cc_block["max20x_limit_tokens"]
            if burn is not None:
                proj_str = (
                    f", projected {_fmt_tokens(int(proj))} ({proj_pct:.0f}%)" if proj else ""
                )
                out.append(f"    burn rate: {_fmt_tokens(int(burn))} tok/min{proj_str}")
            pct_hist = cc_block.get("pct_vs_historical_max")
            hist = cc_block.get("historical_max_tokens")
            if hist and pct_hist is not None:
                out.append(
                    f"    vs. your own history: {pct_hist:.1f}% of max 5h-block "
                    f"({_fmt_tokens(int(hist))})"
                )
        else:
            out.append("  5h block: no active block (no usage in current window)")
        if cc_7d:
            pct_w = cc_7d.get("pct_vs_max20x_limit")
            pct_w_str = f" ({pct_w:.1f}% of Max-20x est.)" if pct_w is not None else ""
            out.append(
                f"  weekly: {_fmt_tokens(cc_7d['tokens'])} tokens  "
                f"{_fmt_usd(cc_7d.get('cost_usd'))}{pct_w_str}"
            )
            out.append(
                f"    window: {cc_7d.get('window_start')} → {cc_7d.get('window_end')} "
                f"({cc_7d.get('n_blocks', 0)} blocks)"
            )
        out.append("  note: weekly % is reset-anchored (since Mon 17:00 local) and")
        out.append("        well-calibrated (2026-05-22 → 10.1% matches claude.ai 10%).")
        out.append("        5h % is approximate: ccusage's block boundary drifts up")
        out.append("        to ~1h from Anthropic's session boundary, so it can")
        out.append("        underestimate the true session %.")
    else:
        out.append("=== Claude quota (sum of observed Stop-hook events) ===")
        out.append(
            f"  last 5h: {_fmt_tokens(five_h['total'])} total  "
            f"(in {_fmt_tokens(five_h['input_tokens'])} / out {_fmt_tokens(five_h['output_tokens'])} / "
            f"cache_read {_fmt_tokens(five_h['cache_read_tokens'])})"
        )
        out.append(
            f"  last 7d: {_fmt_tokens(seven_d['total'])} total  "
            f"(in {_fmt_tokens(seven_d['input_tokens'])} / out {_fmt_tokens(seven_d['output_tokens'])} / "
            f"cache_read {_fmt_tokens(seven_d['cache_read_tokens'])})"
        )
        out.append("  note: ccusage not installed — falling back to Stop-hook accumulator.")
        out.append("        Run `npm i -g ccusage` for per-message accuracy.")

    out.append("")
    out.append("=== Hardware (latest sample) ===")
    if hw:
        out.append(
            f"  CPU {_fmt_pct(hw.get('cpu_percent'))}   "
            f"RAM {_fmt_pct(hw.get('ram_percent'))} ({_fmt_gb(hw.get('ram_used_gb'))}/{_fmt_gb(hw.get('ram_total_gb'))})   "
            f"disk free {_fmt_gb(hw.get('disk_free_gb'))} on {config.DISK_MONITOR_PATH}"
        )
        gpu_util = hw.get("gpu_util_pct")
        if gpu_util is not None:
            out.append(
                f"  GPU util {_fmt_pct(gpu_util)}  "
                f"VRAM {_fmt_gb(hw.get('gpu_mem_used_gb'))}/{_fmt_gb(hw.get('gpu_mem_total_gb'))}  "
                f"temp {hw.get('gpu_temp_c')}°C  power {hw.get('gpu_power_w')} W"
            )
        out.append(f"  sampled at {hw.get('timestamp')}")
    else:
        out.append("  no samples yet — check `systemctl --user status claude-hw-poller.timer`")

    out.append("")
    out.append("=== Agency (autonomous-spend verdict) ===")
    out.append(f"  {agency_verdict['headline']}")
    for r in agency_verdict["reasons"]:
        out.append(f"    - {r}")
    if agency_verdict.get("suggested_session_tokens"):
        out.append(f"    suggested spend this session: ~{_fmt_tokens(agency_verdict['suggested_session_tokens'])} tokens")
    out.append("  (drives `agency: max` repos; standard repos still propose-and-confirm)")

    out.append("")
    out.append("=== Jobs ===")
    running = [j for j in queued if j["status"] == "running"]
    pending = [j for j in queued if j["status"] == "queued"]
    if running:
        out.append("  running:")
        for j in running:
            est = _fmt_tokens(j.get("est_tokens") or 0)
            out.append(
                f"    #{j['id']} [{j['kind']}] {j['project']}  est={est} tokens  "
                f"started {j.get('started_at','?')}"
            )
    else:
        out.append("  running: (none)")
    if pending:
        out.append("  queued:")
        for j in pending:
            est = _fmt_tokens(j.get("est_tokens") or 0)
            out.append(f"    #{j['id']} [{j['kind']}] {j['project']}  est={est}  created {j['created_at']}")
    else:
        out.append("  queued: (none)")

    out.append("")
    out.append("=== Recent completed (last 5) ===")
    if completed:
        for j in completed:
            est = j.get("est_tokens") or 0
            act = j.get("actual_tokens") or 0
            delta = act - est
            sign = "+" if delta >= 0 else ""
            out.append(
                f"  #{j['id']} [{j['kind']}] {j['project']}  {j['status']}  "
                f"est={_fmt_tokens(est)} actual={_fmt_tokens(act)} ({sign}{_fmt_tokens(delta)})"
            )
    else:
        out.append("  (none)")

    return "\n".join(out)


def main() -> int:
    as_json = "--json" in sys.argv
    print(render(as_json=as_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
