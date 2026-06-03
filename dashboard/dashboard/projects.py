"""Filesystem-backed project inspection for the dashboard."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import markdown as md_lib
import yaml

from coordinator.config import PROJECTS_ROOT  # noqa: F401  (machine-config)
from coordinator.readers import tokens_per_day  # noqa: F401  (re-exported)

from .cache import ttl_cache

# arxiv abs/pdf URLs: arxiv.org/abs/YYMM.NNNNN  →  20YY-MM
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{2})(\d{2})\.\d{4,6}")


@ttl_cache(seconds=30)
def list_projects() -> list[dict]:
    """Every directory under ~/projects/research/ that has CLAUDE.md + _meta/.

    Each entry also carries dashboard metadata if a dashboard.yaml is present.
    """
    out = []
    if not PROJECTS_ROOT.exists():
        return out
    for p in sorted(PROJECTS_ROOT.iterdir()):
        if (p / "CLAUDE.md").exists() and (p / "_meta").is_dir():
            entry = {"name": p.name, "path": str(p), "dashboard": _read_dashboard_manifest(p)}
            out.append(entry)
    return out


def _read_dashboard_manifest(project_root: Path) -> Optional[dict]:
    """Read dashboard.yaml at the project root or under dashboard/.
    Returns None when no manifest exists.

    Recognized fields: kind (static|server), entry, title, description,
    tags, port (server kind only), start (server kind only).
    """
    candidates = [
        project_root / "dashboard.yaml",
        project_root / "dashboard" / "dashboard.yaml",
    ]
    for c in candidates:
        if not c.exists():
            continue
        try:
            data = yaml.safe_load(c.read_text()) or {}
            if not isinstance(data, dict):
                continue
        except yaml.YAMLError:
            continue
        kind = data.get("kind", "static")
        # Resolve the served directory (where index.html lives)
        served_dir = c.parent if c.name == "dashboard.yaml" and c.parent.name == "dashboard" else (project_root / "dashboard")
        return {
            "kind": kind,
            "entry": data.get("entry", "index.html"),
            "title": data.get("title", project_root.name),
            "description": data.get("description", ""),
            "tags": data.get("tags", []) or [],
            "port": data.get("port"),
            "start": data.get("start"),
            "manifest_path": str(c),
            "served_dir": str(served_dir),
        }
    return None


def project_dashboard_dir(project_name: str) -> Optional[Path]:
    """Return the on-disk directory whose files we serve at /projects/<n>/dashboard/.
    Returns None if the project has no dashboard manifest.
    """
    project_root = (PROJECTS_ROOT / project_name).resolve()
    if not project_root.exists():
        return None
    mani = _read_dashboard_manifest(project_root)
    if not mani:
        return None
    served = Path(mani["served_dir"]).resolve()
    # Path-traversal guard: served_dir must be inside the project.
    try:
        served.relative_to(project_root)
    except ValueError:
        return None
    if not served.exists() or not served.is_dir():
        return None
    return served


def _read_frontmatter_text(md: Path) -> tuple[dict, str]:
    """YAML frontmatter + body. Handles nested lists / dicts."""
    if not md.exists():
        return {}, ""
    text = md.read_text()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_text, body = parts[1], parts[2]
    try:
        fm = yaml.safe_load(fm_text) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def _extract_diagnostics(body: str) -> Optional[str]:
    if "## Diagnostics" not in body:
        return None
    tail = body.split("## Diagnostics", 1)[1]
    # Cut off at next `##` header.
    chunk = tail.split("\n## ", 1)[0]
    return chunk.strip()


@ttl_cache(seconds=30)
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


def _candidate_files(root: Path) -> list[Path]:
    cdir = root / "raw" / "_candidates"
    if not cdir.exists():
        return []
    return [p for p in cdir.iterdir() if p.is_file() and p.suffix == ".md"]


def _pending_proposal_files(root: Path) -> list[Path]:
    pdir = root / "experiments" / "_proposals"
    if not pdir.exists():
        return []
    # Only files directly in _proposals/ — _done/, _failed/, _expansions/
    # are subfolders the agent files closed proposals into.
    return [p for p in pdir.iterdir() if p.is_file() and p.suffix == ".md"]


def _read_last_digest(root: Path) -> Optional[str]:
    f = root / "_meta" / "last_digest"
    if not f.exists():
        return None
    return f.read_text().strip() or None


def _age_days(iso_or_mtime: float | str | None) -> Optional[float]:
    if iso_or_mtime is None:
        return None
    if isinstance(iso_or_mtime, (int, float)):
        ts = datetime.fromtimestamp(iso_or_mtime, tz=timezone.utc)
    else:
        try:
            ts = datetime.fromisoformat(iso_or_mtime.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0


@ttl_cache(seconds=15)
def project_status(name: str) -> dict:
    """One-row per-project summary used by both the home rollup and the project page."""
    root = PROJECTS_ROOT / name
    cands = _candidate_files(root)
    newest_mtime = max((p.stat().st_mtime for p in cands), default=None)
    pending = _pending_proposal_files(root)
    last_digest = _read_last_digest(root)
    return {
        "name": name,
        "candidates_count": len(cands),
        "candidates_age_days": _age_days(newest_mtime),
        "pending_proposals": len(pending),
        "last_digest": last_digest,
        "last_digest_age_days": _age_days(last_digest),
    }


def all_project_status() -> list[dict]:
    return [project_status(p["name"]) for p in list_projects()]


# --- candidates ---------------------------------------------------------------

_ENTRY_FIELD_RE = re.compile(r"^\s*-\s*(\w+)\s*:\s*(.*)$")


def _arxiv_date_from_url(url: str) -> Optional[str]:
    m = _ARXIV_RE.search(url or "")
    if not m:
        return None
    yy, mm = m.group(1), m.group(2)
    return f"20{yy}-{mm}"


def _parse_candidate_entries(body: str) -> list[dict]:
    """Each `## N. Title` block becomes one dict with title + the `- key: value` fields."""
    entries: list[dict] = []
    current: Optional[dict] = None
    summary_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current is not None:
                if summary_lines:
                    current.setdefault("summary", " ".join(summary_lines).strip())
                entries.append(current)
            title = line[3:].strip()
            # Strip leading "1. " / "12. " numbering.
            title = re.sub(r"^\d+\.\s*", "", title)
            current = {"title": title}
            summary_lines = []
            continue
        if current is None:
            continue
        m = _ENTRY_FIELD_RE.match(line)
        if m:
            current[m.group(1).lower()] = m.group(2).strip()
    if current is not None:
        entries.append(current)
    # Date heuristic for entries that didn't ship a `date:` field.
    for e in entries:
        if not e.get("date"):
            d = _arxiv_date_from_url(e.get("url", ""))
            if d:
                e["date"] = d
                e["date_inferred"] = True
    return entries


@ttl_cache(seconds=20)
def list_candidates(name: str) -> list[dict]:
    """Per project: list candidate files newest first, with parsed entries."""
    root = PROJECTS_ROOT / name
    files = sorted(_candidate_files(root), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files:
        fm, body = _read_frontmatter_text(f)
        entries = _parse_candidate_entries(body)
        out.append(
            {
                "filename": f.name,
                "relpath": f"raw/_candidates/{f.name}",
                "frontmatter": fm,
                "entries": entries,
                "mtime_age_days": _age_days(f.stat().st_mtime),
            }
        )
    return out


# --- literature & concepts ----------------------------------------------------


@ttl_cache(seconds=30)
def list_literature(name: str) -> dict[str, list[dict]]:
    """Group literature notes by their parent dir under `literature/` (papers / repos / posts / ...)."""
    root = PROJECTS_ROOT / name / "literature"
    out: dict[str, list[dict]] = {}
    if not root.exists():
        return out
    for f in sorted(root.rglob("*.md")):
        if f.name.startswith("_"):
            continue
        rel = f.relative_to(root)
        kind = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        fm, _ = _read_frontmatter_text(f)
        out.setdefault(kind, []).append(
            {
                "relpath": str(rel),
                "title": fm.get("title") or f.stem,
                "year": fm.get("year"),
                "venue": fm.get("venue"),
                "relevance": fm.get("relevance"),
                "status": fm.get("status"),
                "added": fm.get("added"),
                "citekey": f.stem,
            }
        )
    # Sort each group by added date desc, then title.
    for k in out:
        out[k].sort(
            key=lambda e: (str(e.get("added") or ""), e.get("title") or ""),
            reverse=True,
        )
    return out


@ttl_cache(seconds=30)
def list_concepts(name: str) -> list[dict]:
    root = PROJECTS_ROOT / name / "concepts"
    out: list[dict] = []
    if not root.exists():
        return out
    for f in sorted(root.glob("*.md")):
        if f.name.startswith("_"):
            continue
        fm, _ = _read_frontmatter_text(f)
        used_by = fm.get("used_by") or []
        sources = fm.get("sources") or []
        out.append(
            {
                "name": f.stem,
                "status": fm.get("status"),
                "tags": fm.get("tags") or [],
                "used_by_count": len(used_by) if isinstance(used_by, list) else 0,
                "sources_count": len(sources) if isinstance(sources, list) else 0,
            }
        )
    return out


_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _render_wikilinks(html_or_text: str, project_name: str) -> str:
    """Turn [[concepts/foo]] and [[literature/papers/bar]] into dashboard links."""

    def repl(m: re.Match) -> str:
        target = m.group(1).strip()
        label = (m.group(2) or target).strip()
        if target.startswith("concepts/"):
            slug = target[len("concepts/"):]
            href = f"/project/{project_name}/concepts/{slug}"
        elif target.startswith("literature/"):
            rel = target[len("literature/"):]
            if not rel.endswith(".md"):
                rel = rel + ".md"
            href = f"/project/{project_name}/literature/{rel}"
        else:
            return m.group(0)
        return f'<a href="{href}">{label}</a>'

    return _WIKILINK_RE.sub(repl, html_or_text)


def render_markdown(text: str, project_name: str) -> str:
    """Markdown → HTML with wikilink rewriting."""
    text = _render_wikilinks(text, project_name)
    return md_lib.markdown(
        text,
        extensions=["extra", "sane_lists", "tables", "fenced_code", "toc"],
    )


@ttl_cache(seconds=20)
def read_literature_note(name: str, relpath: str) -> Optional[dict]:
    root = PROJECTS_ROOT / name / "literature"
    target = (root / relpath).resolve()
    # Path-traversal guard.
    if root.resolve() not in target.parents and target != root.resolve():
        return None
    if not target.exists() or target.suffix != ".md":
        return None
    fm, body = _read_frontmatter_text(target)
    return {
        "relpath": relpath,
        "frontmatter": fm,
        "html": render_markdown(body, name),
    }


# --- search, snippets, attention feed ----------------------------------------


def _first_non_heading_paragraph(body: str, max_chars: int = 220) -> str:
    """Pull the first prose paragraph after the H1 for a snippet."""
    paragraphs = []
    buf: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("```"):
            if buf:
                paragraphs.append(" ".join(buf).strip())
                buf = []
            continue
        if not s:
            if buf:
                paragraphs.append(" ".join(buf).strip())
                buf = []
            continue
        buf.append(s)
    if buf:
        paragraphs.append(" ".join(buf).strip())
    for p in paragraphs:
        if len(p) >= 40:
            return (p[: max_chars - 1] + "…") if len(p) > max_chars else p
    return paragraphs[0] if paragraphs else ""


def snippet_for_concept(project: str, slug: str) -> Optional[str]:
    f = PROJECTS_ROOT / project / "concepts" / f"{slug}.md"
    if not f.exists():
        return None
    _, body = _read_frontmatter_text(f)
    return _first_non_heading_paragraph(body)


def snippet_for_literature(project: str, relpath: str) -> Optional[str]:
    f = PROJECTS_ROOT / project / "literature" / relpath
    if not f.exists():
        return None
    fm, body = _read_frontmatter_text(f)
    snippet = _first_non_heading_paragraph(body)
    title = fm.get("title")
    if title and not snippet:
        return title
    return snippet or title or ""


@ttl_cache(seconds=20)
def search_all(q: str, limit: int = 20) -> list[dict]:
    """Cheap fuzzy-ish search across literature, concepts, experiments. All projects."""
    needle = q.lower().strip()
    if not needle:
        return []
    hits: list[tuple[int, dict]] = []
    for proj in list_projects():
        name = proj["name"]
        root = PROJECTS_ROOT / name
        # concepts
        cdir = root / "concepts"
        if cdir.exists():
            for f in cdir.glob("*.md"):
                if f.name.startswith("_"):
                    continue
                slug = f.stem
                fm, _ = _read_frontmatter_text(f)
                hay = " ".join([slug, fm.get("name") or "", " ".join(fm.get("tags") or [])]).lower()
                score = _score(needle, slug.lower(), hay)
                if score:
                    hits.append((score, {
                        "kind": "concept",
                        "title": fm.get("name") or slug,
                        "where": name,
                        "url": f"/project/{name}/concepts/{slug}",
                    }))
        # literature
        lroot = root / "literature"
        if lroot.exists():
            for f in lroot.rglob("*.md"):
                if f.name.startswith("_"):
                    continue
                fm, _ = _read_frontmatter_text(f)
                title = str(fm.get("title") or f.stem)
                authors = ""
                if isinstance(fm.get("authors"), list):
                    authors = " ".join(str(a) for a in fm["authors"])
                hay = " ".join([f.stem, title, authors, " ".join(fm.get("tags") or [])]).lower()
                score = _score(needle, f.stem.lower(), hay)
                if score:
                    rel = f.relative_to(lroot)
                    hits.append((score, {
                        "kind": "literature",
                        "title": title,
                        "where": f"{name} · {rel}",
                        "url": f"/project/{name}/literature/{rel}",
                    }))
        # experiments
        edir = root / "experiments"
        if edir.exists():
            for p in edir.iterdir():
                if not p.is_dir() or p.name.startswith("_"):
                    continue
                readme = p / "README.md"
                fm, _ = _read_frontmatter_text(readme) if readme.exists() else ({}, "")
                hyp = str(fm.get("hypothesis") or "")
                hay = (p.name + " " + hyp).lower()
                score = _score(needle, p.name.lower(), hay)
                if score:
                    hits.append((score, {
                        "kind": "experiment",
                        "title": p.name,
                        "where": name + (" · " + hyp[:60] + "…" if hyp else ""),
                        "url": f"/project/{name}",
                    }))
    hits.sort(key=lambda h: -h[0])
    return [h[1] for h in hits[:limit]]


def _score(needle: str, primary: str, haystack: str) -> int:
    """Tiny scoring: prefix of primary > primary contains > haystack contains."""
    if not needle:
        return 0
    if primary.startswith(needle):
        return 100 + (50 - min(len(primary), 50))
    if needle in primary:
        return 60
    if needle in haystack:
        return 30
    # Subsequence fallback (very loose).
    i = 0
    for c in haystack:
        if i < len(needle) and c == needle[i]:
            i += 1
    if i == len(needle):
        return 10
    return 0


def build_attention_feed(rollup: list[dict]) -> list[dict]:
    """Per-project signals worth surfacing on the home page."""
    out: list[dict] = []
    for p in rollup:
        n = p["name"]
        if p.get("candidates_count", 0) > 0:
            age = p.get("candidates_age_days")
            age_str = f" ({age:.1f}d old)" if age is not None else ""
            out.append({
                "what": f"{p['candidates_count']} un-curated candidate(s) in {n}",
                "where": f"raw/_candidates/{age_str}",
                "url": f"/project/{n}/candidates",
            })
        if p.get("pending_proposals", 0) >= 3:
            out.append({
                "what": f"{p['pending_proposals']} pending proposal(s) in {n}",
                "where": "experiments/_proposals/",
                "url": f"/project/{n}",
            })
        last = p.get("last_digest_age_days")
        if last is not None and last > 14:
            out.append({
                "what": f"digest hasn't run in {last:.0f} days for {n}",
                "where": "_meta/last_digest",
                "url": f"/project/{n}",
            })
    return out


@ttl_cache(seconds=20)
def read_concept(name: str, slug: str) -> Optional[dict]:
    root = PROJECTS_ROOT / name / "concepts"
    target = (root / f"{slug}.md").resolve()
    if root.resolve() not in target.parents:
        return None
    if not target.exists():
        return None
    fm, body = _read_frontmatter_text(target)
    # Find back-references: literature notes that wikilink this concept.
    backrefs: list[str] = []
    lit_root = PROJECTS_ROOT / name / "literature"
    needle = f"[[concepts/{slug}]]"
    if lit_root.exists():
        for f in lit_root.rglob("*.md"):
            try:
                if needle in f.read_text():
                    backrefs.append(str(f.relative_to(lit_root)))
            except OSError:
                continue
    return {
        "slug": slug,
        "frontmatter": fm,
        "html": render_markdown(body, name),
        "literature_backrefs": sorted(backrefs),
    }
