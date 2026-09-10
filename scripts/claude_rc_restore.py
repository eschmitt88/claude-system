#!/usr/bin/env python3
"""Snapshot live Remote Control sessions and restore them into tmux after a reboot.

Subcommands:
    snapshot            record the interactive sessions that currently have Remote
                        Control on (from ~/.claude/sessions/*.json) into the manifest;
                        entries not seen for --prune-minutes are dropped
    restore [--dry-run] resume every manifest session that is not already running,
                        one tmux window each in tmux session "cc"
    seed ID [ID ...]    add sessions to the manifest by hand (e.g. from
                        claude_sessions_lost_at_boot.py --sh)
    list                print the manifest

Plain `claude --resume <id>` reattaches to the same claude.ai/code entry through
the transcript's reconnection record, so no --remote-control flag is needed.

Wired up by scripts/systemd/claude-rc-snapshot.timer (every 2 min) and
claude-rc-restore.service (at boot, ExecStop snapshots at shutdown).
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SESSIONS = CLAUDE_DIR / "sessions"
MANIFEST = CLAUDE_DIR / "rc-restore" / "manifest.json"
TMUX_SESSION = "cc"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def proc_alive(pid, proc_start):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
    except OSError:
        return False
    # field 22 (1-based) is starttime; after the comm field it is index 19
    return proc_start is None or str(fields[19]) == str(proc_start)


def live_sessions():
    """Return {sessionId: record} for interactive sessions with a live process."""
    out = {}
    for f in SESSIONS.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("kind") != "interactive" or not d.get("sessionId"):
            continue
        if not proc_alive(d.get("pid"), d.get("procStart")):
            continue
        out[d["sessionId"]] = d
    return out


def load_manifest():
    try:
        return json.loads(MANIFEST.read_text())
    except (OSError, json.JSONDecodeError):
        return {"sessions": {}}


def save_manifest(m):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    m["updatedAt"] = now_iso()
    tmp.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, MANIFEST)


def cmd_snapshot(args):
    m = load_manifest()
    sessions = m.setdefault("sessions", {})
    now = time.time()
    seen = 0
    for sid, d in live_sessions().items():
        if not args.all and (not d.get("bridgeSessionId") or d.get("entrypoint") != "cli"):
            # sessions served by `claude remote-control` (entrypoint sdk-cli) are the
            # server's to bring back; only terminal-launched sessions go to tmux
            continue
        seen += 1
        entry = sessions.setdefault(sid, {})
        entry.update({
            "cwd": d.get("cwd"),
            "name": d.get("name"),
            "bridgeSessionId": d.get("bridgeSessionId"),
            "lastSeen": now,
            "lastSeenIso": now_iso(),
        })
    cutoff = now - args.prune_minutes * 60
    pruned = [sid for sid, e in sessions.items() if e.get("lastSeen", 0) < cutoff]
    for sid in pruned:
        del sessions[sid]
    save_manifest(m)
    print(f"snapshot: {seen} live, {len(sessions)} in manifest, pruned {len(pruned)}")


def cmd_seed(args):
    m = load_manifest()
    sessions = m.setdefault("sessions", {})
    for sid in args.ids:
        sessions.setdefault(sid, {}).update({
            "cwd": args.cwd, "name": args.name, "lastSeen": time.time(),
            "lastSeenIso": now_iso(), "seeded": True,
        })
    save_manifest(m)
    print(f"seeded {len(args.ids)}; manifest now {len(sessions)}")


def cmd_list(args):
    m = load_manifest()
    print(f"# manifest {MANIFEST} updated {m.get('updatedAt')}")
    for sid, e in sorted(m.get("sessions", {}).items(), key=lambda kv: kv[1].get("lastSeen", 0), reverse=True):
        print(f"{sid}  {e.get('lastSeenIso','?')}  {e.get('cwd')}  {e.get('name') or ''}")


def tmux(*a, check=True):
    return subprocess.run(["tmux", *a], check=check, capture_output=True, text=True)


def transcript_title(sid, cwd):
    """Last custom title recorded in the session transcript, if any."""
    slug = "-" + cwd.strip("/").replace("/", "-")
    path = CLAUDE_DIR / "projects" / slug / f"{sid}.jsonl"
    title = None
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if '"custom-title"' in line:
                    try:
                        title = json.loads(line).get("customTitle") or title
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return title


def cmd_restore(args):
    m = load_manifest()
    running = live_sessions()
    todo = [(sid, e) for sid, e in m.get("sessions", {}).items() if sid not in running]
    todo.sort(key=lambda kv: kv[1].get("lastSeen", 0), reverse=True)
    if not todo:
        print("restore: nothing to do")
        return
    if args.dry_run:
        for sid, e in todo:
            print(f"would resume {sid} in {e.get('cwd')} ({e.get('name') or 'unnamed'})")
        return
    if tmux("has-session", "-t", TMUX_SESSION, check=False).returncode != 0:
        tmux("new-session", "-d", "-s", TMUX_SESSION, "-c", str(Path.home()), "-n", "shell")
    for i, (sid, e) in enumerate(todo):
        cwd = e.get("cwd") or str(Path.home())
        if not Path(cwd).is_dir():
            print(f"skip {sid}: cwd {cwd} missing", file=sys.stderr)
            continue
        # keep the pane open on failure so the error is readable; close on clean exit
        inner = (f"claude --resume {shlex.quote(sid)}; rc=$?; "
                 f"if [ $rc -ne 0 ]; then echo; echo \"[claude exited $rc] press Enter to close\"; read -r; fi")
        win = (transcript_title(sid, cwd) or e.get("name") or sid[:8]).replace(":", "-")[:24]
        tmux("new-window", "-t", TMUX_SESSION, "-n", win, "-c", cwd, f"bash -c {shlex.quote(inner)}")
        print(f"resumed {sid} -> tmux {TMUX_SESSION}:{win}", flush=True)
        if i < len(todo) - 1 and args.stagger > 0:
            time.sleep(args.stagger)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("--prune-minutes", type=float, default=30)
    s.add_argument("--all", action="store_true", help="include sessions without Remote Control and server-mode sessions")
    s.set_defaults(fn=cmd_snapshot)
    r = sub.add_parser("restore"); r.add_argument("--dry-run", action="store_true")
    r.add_argument("--stagger", type=float, default=3, help="seconds between launches")
    r.set_defaults(fn=cmd_restore)
    d = sub.add_parser("seed"); d.add_argument("ids", nargs="+"); d.add_argument("--cwd", default="/mnt/projects")
    d.add_argument("--name", default=None); d.set_defaults(fn=cmd_seed)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
