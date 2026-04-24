"""Idempotent schema initialization. Called by install.sh."""
from __future__ import annotations

from . import DB_PATH
from .db import init_schema


def main() -> int:
    init_schema()
    print(f"coordinator schema ready at {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
