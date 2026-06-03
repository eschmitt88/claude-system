"""`claude-coordinator-agency` CLI. Prints the resource-aware agency
verdict (GO / SLOW / HOLD) used by `agency: max` repos to decide whether to
proceed autonomously. Pass --json for structured output.
"""
from __future__ import annotations

import json
import sys

from .agency import verdict


def main() -> int:
    as_json = "--json" in sys.argv[1:]
    v = verdict()
    if as_json:
        print(json.dumps(v, indent=2))
        return 0
    print(f"Agency: {v['headline']}")
    for r in v["reasons"]:
        print(f"  - {r}")
    if v.get("suggested_session_tokens"):
        print(f"  suggested spend this session: ~{v['suggested_session_tokens']:,} tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
