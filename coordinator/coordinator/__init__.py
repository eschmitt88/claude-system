"""Resource coordinator for claude-system.

A single sqlite database at ~/.claude/state.db is the source of truth for:
- Claude quota state (5h + weekly windows)
- Hardware samples (CPU/RAM/disk/GPU)

Skills consult the coordinator via /headroom; the agency verdict turns
quota + hardware state into a GO/SLOW/HOLD recommendation.
"""
from __future__ import annotations

from pathlib import Path

DB_PATH = Path.home() / ".claude" / "state.db"
