"""Resource coordinator for claude-system.

A single sqlite database at ~/.claude/state.db is the source of truth for:
- Claude quota state (5h + weekly windows)
- Hardware samples (CPU/RAM/disk/GPU)
- Job queue (declared work + estimated cost + status)
- Decisions log (admit/defer)

Skills consult the coordinator via /status and /plan; long-running
skills declare jobs before spending tokens.
"""
from __future__ import annotations

from pathlib import Path

DB_PATH = Path.home() / ".claude" / "state.db"
