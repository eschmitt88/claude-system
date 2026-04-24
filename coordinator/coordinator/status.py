"""`claude-coordinator-status` CLI. Fast summary for /status skill.

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
from datetime import datetime, timezone

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


def render(as_json: bool = False) -> str:
    five_h = tokens_in_last(5 * 3600)
    seven_d = tokens_in_last(7 * 24 * 3600)
    hw = latest_hardware_sample()
    queued = queued_jobs(limit=10)
    completed = recent_completed_jobs(limit=5)

    if as_json:
        return json.dumps(
            {
                "tokens_5h": five_h,
                "tokens_7d": seven_d,
                "hardware": hw,
                "running_and_queued": queued,
                "recent_completed": completed,
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
            default=str,
        )

    out = []
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
    out.append("  note: Anthropic exposes no API for true rolling-window quota;")
    out.append("        these are accumulated locally. Use ccusage for reset times.")

    out.append("")
    out.append("=== Hardware (latest sample) ===")
    if hw:
        out.append(
            f"  CPU {_fmt_pct(hw.get('cpu_percent'))}   "
            f"RAM {_fmt_pct(hw.get('ram_percent'))} ({_fmt_gb(hw.get('ram_used_gb'))}/{_fmt_gb(hw.get('ram_total_gb'))})   "
            f"disk free {_fmt_gb(hw.get('disk_free_gb'))} on /mnt/projects"
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
