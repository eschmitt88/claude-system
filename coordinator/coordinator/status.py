"""`claude-coordinator-status` CLI. Fast summary for /headroom skill.

Prints:
- Claude token usage over the trailing 5h and 7d windows (state.db totals).
- Latest hardware sample with per-resource units.
- The box schedule: running tracked jobs, upcoming heavy jobs, GPU-quiet window.
- The agency (autonomous-spend) verdict.

Pure read path — no writes, no policy. Should return in <1s.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from . import agency, ccusage, config, jobs
from .readers import latest_hardware_sample, tokens_in_last


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


def _safe_brief(hw):
    try:
        return jobs.brief(hw, hours=12)
    except Exception:
        return None


def _basis_str(w: dict) -> str:
    basis = w.get("limit_basis")
    if basis == "observed":
        return " — observed+delta"
    if basis == "calibrated":
        return " — calibrated est."
    return " of Max-20x est."


def _observed_line(label: str, w: Optional[dict]) -> Optional[str]:
    if not w or w.get("observed_pct") is None:
        return None
    age = w.get("observation_age_min") or 0
    age_s = f"{age}m" if age < 120 else f"{age / 60:.0f}h"
    stale = "  (stale anchor)" if age > 24 * 60 else ""
    lim = w.get("calibrated_limit_usd")
    lim_s = f"${lim:,.0f}" if lim else "static"
    return (
        f"    {label} anchor: {w['observed_pct']:.0f}% reported {age_s} ago "
        f"+ {w.get('delta_pct') or 0:.1f}% since  "
        f"[ceiling {lim_s}, {w.get('calibration_source')}]{stale}"
    )


def render(as_json: bool = False) -> str:
    # ccusage calls are the slowest part (~0.4s each) — run them concurrently.
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_block = ex.submit(ccusage.active_block)
        f_7d = ex.submit(ccusage.weekly_anchored)
        five_h = tokens_in_last(5 * 3600)
        seven_d = tokens_in_last(7 * 24 * 3600)
        hw = latest_hardware_sample()
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
                "schedule_brief": _safe_brief(hw),
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
            default=str,
        )

    out = []
    if cc_block or cc_7d:
        observed = any((w or {}).get("limit_basis") in ("observed", "calibrated")
                       for w in (cc_block, cc_7d))
        src = ("Anthropic-reported % via status line + transcript spend since"
               if observed else "via ccusage — reads ~/.claude/projects/*.jsonl")
        out.append(f"=== Claude quota ({src}) ===")
        if cc_block:
            pct = cc_block.get("pct_vs_max20x_limit")
            pct_str = f" ({pct:.1f}%{_basis_str(cc_block)})" if pct is not None else ""
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
            pct_w_str = f" ({pct_w:.1f}%{_basis_str(cc_7d)})" if pct_w is not None else ""
            out.append(
                f"  weekly: {_fmt_tokens(cc_7d['tokens'])} tokens  "
                f"{_fmt_usd(cc_7d.get('cost_usd'))}{pct_w_str}"
            )
            n = (f"{cc_7d['n_blocks']} blocks" if cc_7d.get("n_blocks") is not None
                 else f"{cc_7d.get('n_messages', 0)} messages")
            out.append(
                f"    window: {cc_7d.get('window_start')} → {cc_7d.get('window_end')} ({n})"
            )
        for label, w in (("5h", cc_block), ("weekly", cc_7d)):
            line = _observed_line(label, w)
            if line:
                out.append(line)
        if not observed:
            out.append("  note: no status-line reading yet — % is ccusage spend against a")
            out.append("        static ceiling (5h % especially rough: hour-rounded blocks).")
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
    out.append("=== Scheduled jobs (job ledger; `claude-coordinator-jobs` for detail) ===")
    try:
        for line in jobs.brief(hw, hours=12).splitlines():
            out.append("  " + line)
    except Exception as e:  # ledger is optional context, never fatal
        out.append(f"  unavailable ({e.__class__.__name__})")

    out.append("")
    out.append("=== Agency (autonomous-spend verdict) ===")
    out.append(f"  {agency_verdict['headline']}")
    for r in agency_verdict["reasons"]:
        out.append(f"    - {r}")
    if agency_verdict.get("suggested_session_tokens"):
        out.append(f"    suggested spend this session: ~{_fmt_tokens(agency_verdict['suggested_session_tokens'])} tokens")
    out.append("  (drives `agency: max` repos; standard repos still propose-and-confirm)")

    return "\n".join(out)


def main() -> int:
    as_json = "--json" in sys.argv
    print(render(as_json=as_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
