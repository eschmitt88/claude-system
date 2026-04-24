"""Filesystem-backed project inspection for the dashboard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PROJECTS_ROOT = Path.home() / "projects" / "research"


def list_projects() -> list[dict]:
    """Every directory under ~/projects/research/ that has CLAUDE.md + _meta/."""
    out = []
    if not PROJECTS_ROOT.exists():
        return out
    for p in sorted(PROJECTS_ROOT.iterdir()):
        if (p / "CLAUDE.md").exists() and (p / "_meta").is_dir():
            out.append({"name": p.name, "path": str(p)})
    return out


def _read_frontmatter_text(md: Path) -> tuple[dict, str]:
    """Very small frontmatter parser — key: value only."""
    if not md.exists():
        return {}, ""
    text = md.read_text()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_text, body = parts[1], parts[2]
    fm: dict = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"')
    return fm, body


def _extract_diagnostics(body: str) -> Optional[str]:
    if "## Diagnostics" not in body:
        return None
    tail = body.split("## Diagnostics", 1)[1]
    # Cut off at next `##` header.
    chunk = tail.split("\n## ", 1)[0]
    return chunk.strip()


def project_cycles(name: str, limit: int = 10) -> list[dict]:
    root = PROJECTS_ROOT / name
    exp_root = root / "experiments"
    if not exp_root.exists():
        return []
    cycles = []
    folders = sorted(
        [p for p in exp_root.iterdir() if p.is_dir() and not p.name.startswith("_")],
        reverse=True,
    )
    for p in folders[:limit]:
        readme = p / "README.md"
        fm, body = _read_frontmatter_text(readme)
        metrics = {}
        mpath = p / "metrics.json"
        if mpath.exists():
            try:
                metrics = json.loads(mpath.read_text() or "{}")
            except json.JSONDecodeError:
                metrics = {}
        fmetrics = {}
        fmpath = p / "final_metrics.json"
        if fmpath.exists():
            try:
                fmetrics = json.loads(fmpath.read_text() or "{}")
            except json.JSONDecodeError:
                fmetrics = {}
        cycles.append(
            {
                "slug": p.name,
                "path": str(p),
                "status": fm.get("status", "?"),
                "hypothesis": fm.get("hypothesis", ""),
                "result": fm.get("result", ""),
                "metrics": metrics,
                "final_metrics": fmetrics,
                "diagnostics": _extract_diagnostics(body),
            }
        )
    return cycles


def project_inbox_count(name: str) -> int:
    inbox = PROJECTS_ROOT / name / "literature" / "inbox"
    if not inbox.exists():
        return 0
    return sum(1 for _ in inbox.iterdir() if _.is_file())
