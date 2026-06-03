"""Resolved machine-specific configuration for claude-system.

Single source of truth for the handful of paths/values that vary per
machine. Every value has a sensible default, so the system works with no
config at all. Override any of them in ``~/.claude/.env`` (shell syntax);
``install.sh`` bakes those values into the systemd units, and hooks source
the same file.

Read order for each value: environment variable → computed default.
"""
from __future__ import annotations

import os
from pathlib import Path


def _first_existing(*paths) -> str | None:
    for p in paths:
        if p and Path(p).expanduser().exists():
            return str(Path(p).expanduser())
    return None


# Root under which research projects live (each project is a subdirectory).
PROJECTS_ROOT = Path(
    os.environ.get("PROJECTS_ROOT") or (Path.home() / "projects" / "research")
).expanduser()

# Filesystem path sampled for free-disk in /headroom and the dashboard.
# Defaults to the projects volume when it exists, else $HOME.
DISK_MONITOR_PATH = (
    os.environ.get("DISK_MONITOR_PATH")
    or _first_existing(Path.home() / "projects", Path.home())
    or str(Path.home())
)

# Dashboard bind address (host:port). 0.0.0.0 exposes it on the LAN.
DASHBOARD_BIND = os.environ.get("CLAUDE_DASHBOARD_BIND", "0.0.0.0:8080")
