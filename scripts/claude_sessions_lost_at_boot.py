#!/usr/bin/env python3
"""List Claude Code sessions that were alive at the last reboot and print resume commands.

A session's transcript (~/.claude/projects/<cwd-slug>/<id>.jsonl) stops being
written the moment its process dies, so any transcript whose mtime falls in the
minute the machine went down was an open session killed by the reboot.

Usage:
    claude_sessions_lost_at_boot.py            # sessions killed at the last boot
    claude_sessions_lost_at_boot.py --days 3   # any session touched in the last 3 days
    claude_sessions_lost_at_boot.py --sh       # print only the resume commands
    claude_sessions_lost_at_boot.py --tmux     # one tmux window per session (survives VS Code disconnects)

Resuming with plain `claude --resume <id>` is enough to bring a Remote Control
session back onto the same claude.ai/code entry: the transcript carries a
reconnection record (docs: remote-control.md, "Resume sessions after stopping
the server"). Do not pass --remote-control on top of --resume.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
SKIP_SLUGS = {"-mnt-projects--claude-p-cwd"}  # batch `claude -p` cwd, never interactive


def boot_time() -> float:
    with open("/proc/stat") as fh:
        for line in fh:
            if line.startswith("btime "):
                return float(line.split()[1])
    raise SystemExit("no btime in /proc/stat")


def summarize(path: Path):
    """Return (custom_title, remote_control, cwd, first_user_message)."""
    title = None
    rc = False
    cwd = None
    first = None
    with open(path, errors="replace") as fh:
        for line in fh:
            if not rc and ("bridgeSessionId" in line or "remote-control" in line or "remoteControl" in line):
                rc = True
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "custom-title":
                title = d.get("customTitle") or title
            if cwd is None and d.get("cwd"):
                cwd = d["cwd"]
            if first is None and d.get("type") == "user":
                c = d.get("message", {}).get("content")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                if isinstance(c, str) and c.strip() and not c.startswith("<"):
                    first = re.sub(r"\s+", " ", c.strip())[:80]
    return title, rc, cwd, first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, help="list every session touched in the last N days instead")
    ap.add_argument("--window", type=int, default=180, help="seconds around boot to count as 'killed at boot'")
    ap.add_argument("--sh", action="store_true", help="print only shell commands")
    ap.add_argument("--tmux", action="store_true", help="emit tmux commands: session 'cc', one window per resumed session")
    args = ap.parse_args()

    bt = boot_time()
    running = set()
    try:
        out = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True, timeout=15).stdout
        for m in re.finditer(r'"sessionId"\s*:\s*"([0-9a-f-]{36})"', out):
            running.add(m.group(1))
    except Exception:
        pass
    for f in (Path.home() / ".claude" / "sessions").glob("*.json"):
        try:
            running.add(json.loads(f.read_text()).get("sessionId"))
        except Exception:
            pass

    rows = []
    for slug_dir in PROJECTS.iterdir():
        if not slug_dir.is_dir() or slug_dir.name in SKIP_SLUGS:
            continue
        for jl in slug_dir.glob("*.jsonl"):
            m = jl.stat().st_mtime
            if args.days:
                if m < time.time() - args.days * 86400:
                    continue
            elif not (bt - args.window <= m <= bt + args.window):
                continue
            sid = jl.stem
            if sid in running:
                continue
            title, rc, cwd, first = summarize(jl)
            rows.append((m, sid, title, rc, cwd or slug_dir.name, first, jl.stat().st_size))

    rows.sort(reverse=True)
    if not rows:
        print("no matching sessions", file=sys.stderr)
        return
    if not args.sh:
        when = datetime.fromtimestamp(bt, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"# boot at {when}; {len(rows)} session(s) " + ("touched recently" if args.days else "killed at boot"))
        print()
    if args.tmux:
        print("tmux has-session -t cc 2>/dev/null || tmux new-session -d -s cc -c /mnt/projects")
    for m, sid, title, rc, cwd, first, size in rows:
        label = title or (first or "(untitled)")
        if not args.sh and not args.tmux:
            ts = datetime.fromtimestamp(m, timezone.utc).strftime("%m-%d %H:%M")
            print(f"# {ts}  {sid[:8]}  {size/1e6:6.1f} MB  rc={'y' if rc else 'n'}  {cwd}\n#   {label}")
        cmd = f"claude --resume {sid}"
        if args.tmux:
            win = re.sub(r"[^A-Za-z0-9._-]+", "-", (title or sid[:8]))[:20]
            print(f"tmux new-window -t cc -n {win!r} -c {cwd!r} {cmd!r}")
        else:
            print(f"(cd {cwd} && {cmd})")
            if not args.sh:
                print()


if __name__ == "__main__":
    main()
