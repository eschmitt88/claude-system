#!/usr/bin/env python3
"""kg_lint.py — mechanical knowledge-graph + HCE checks for /lint.

Deterministic port of the 13 checks that used to live as prose in
lint/SKILL.md (instruction-ablation-program, phase 3). The skill runs
this script and interprets/prioritizes the findings; judgment-shaped
calls (whether to promote a MoC, whether a cluster needs consolidation)
stay with the model, fed by the cluster stats reported here.

Usage:
    python kg_lint.py [--root DIR] [--json]

Needs PyYAML — run via the coordinator venv:
    ~/claude-system/coordinator/.venv/bin/python ~/claude-system/scripts/kg_lint.py

Exit codes: 0 clean-or-warnings, 1 HCE hard failure, 2 not a project.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

TODAY = dt.date.today()
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]+)?\]\]")
ANCHOR_RE = re.compile(
    r"(\S+\.(?:py|qmd|json|yaml|csv|parquet):\S+"   # file:line / file:key refs
    r"|\[\[(?:literature|concepts)/[^\]]+\]\]"       # graph wikilinks
    r"|results/\S+)"                                 # results pointers
)
PLACEHOLDER_DIAG_RE = re.compile(
    r"intended_effect_confirmed:\s*(<|$|\s*$)", re.M
)
STALE_CANDIDATE_DAYS = 14
STALE_LIT_DAYS = 30
STALE_PROPOSAL_DAYS = 14
STALE_EXPANSION_DAYS = 7
COSTLY_SESSION_TOKENS = 500_000
MOC_CLUSTER_MIN = 5


def frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1])
        return fm if isinstance(fm, dict) else {}
    except yaml.YAMLError:
        return {}


def body(path: Path) -> str:
    text = path.read_text(errors="replace")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def file_date(path: Path, fm: dict, *keys: str) -> dt.date | None:
    for k in keys:
        v = fm.get(k)
        if v:
            try:
                return dt.date.fromisoformat(str(v)[:10])
            except ValueError:
                pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        try:
            return dt.date.fromisoformat(m.group(1))
        except ValueError:
            pass
    try:
        return dt.date.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def age_days(d: dt.date | None) -> int | None:
    return (TODAY - d).days if d else None


def find_root(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / "CLAUDE.md").is_file() and (p / "_meta").is_dir():
            return p
    return None


class Lint:
    def __init__(self, root: Path):
        self.root = root
        self.report: dict = {"root": str(root)}
        self.exp_dirs = sorted(
            d for d in (root / "experiments").glob("????-??-??-*") if d.is_dir()
        ) if (root / "experiments").is_dir() else []
        self.mode = "experiments" if self.exp_dirs else "research"
        self.budget = frontmatter_yaml(root / "budget.yaml")
        self.hce_active = self.mode == "experiments" and (
            (root / "splits.yaml").is_file()
            or any((d / "test").exists() for d in self.exp_dirs)
            or "hce" in str(self.budget.get("evaluation_mode", ""))
            or "evaluation_mode: hce" in read_or_empty(root / "CLAUDE.md")
        )
        self.lit = sorted((root / "literature").rglob("*.md")) if (root / "literature").is_dir() else []
        self.concepts = sorted((root / "concepts").glob("*.md")) if (root / "concepts").is_dir() else []
        self.concepts = [c for c in self.concepts if not c.name.startswith("_")]
        self.mocs = sorted((root / "mocs").glob("*.md")) if (root / "mocs").is_dir() else []
        self.lit_fm = {p: frontmatter(p) for p in self.lit}
        self.concept_fm = {p: frontmatter(p) for p in self.concepts}
        self.graph_bodies = {
            p: body(p) for p in [*self.concepts, *self.mocs] if p.is_file()
        }

    # -- engagement (check 1 definition, reused by 2 and 7) -----------------
    def engaged(self, note: Path) -> bool:
        fm = self.lit_fm.get(note, {})
        if fm.get("related_experiments") or fm.get("related_concepts"):
            return True
        b = body(note)
        m = re.search(r"^## Follow-up\s*$(.*?)(?=^## |\Z)", b, re.M | re.S)
        if m and re.search(r"^\s*-\s+(?!\.\.\.)\S", m.group(1), re.M):
            return True
        slug = note.stem
        rel = note.relative_to(self.root).with_suffix("").as_posix()
        for gb in self.graph_bodies.values():
            if f"[[{rel}]]" in gb or f"[[{rel}|" in gb:
                return True
        for fm2 in self.concept_fm.values():
            srcs = (fm2.get("sources") or []) + (fm2.get("source_papers") or [])
            if any(slug in str(s) for s in srcs):
                return True
        return False

    def run(self) -> dict:
        r = self.report
        r["mode"] = self.mode
        r["hce_active"] = self.hce_active

        engaged = {p: self.engaged(p) for p in self.lit}

        r["orphans"] = [rel(self.root, p) for p, e in engaged.items() if not e]

        r["high_relevance_no_followup"] = [
            {"path": rel(self.root, p), "relevance": self.lit_fm[p].get("relevance")}
            for p, e in engaged.items()
            if not e and (self.lit_fm[p].get("relevance") or 0) >= 4
        ]
        if self.mode == "experiments":
            r["in_graph_but_no_experiment"] = [
                rel(self.root, p)
                for p, e in engaged.items()
                if e
                and (self.lit_fm[p].get("relevance") or 0) >= 4
                and not self.lit_fm[p].get("related_experiments")
            ]

        # dead wikilinks
        dead = []
        all_md = [p for p in self.root.rglob("*.md")
                  if ".worktrees" not in p.parts and ".venv" not in p.parts
                  and "raw" not in p.parts]
        stems = {p.stem for p in all_md}
        rels = {p.relative_to(self.root).with_suffix("").as_posix() for p in all_md}
        for p in all_md:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                for m in WIKILINK_RE.finditer(line):
                    target = m.group(1).strip()
                    if target in rels or target.rsplit("/", 1)[-1] in stems:
                        continue
                    dead.append({"file": rel(self.root, p), "line": i, "target": target})
        r["dead_wikilinks"] = dead

        r["concepts_without_sources"] = [
            rel(self.root, p)
            for p, fm in self.concept_fm.items()
            if not (fm.get("sources") or fm.get("source_papers"))
        ]

        # MoC cluster stats (mechanical part of check 5; judgment stays upstream)
        tag_map: dict[str, list[str]] = {}
        for p, fm in self.concept_fm.items():
            for t in fm.get("tags") or []:
                tag_map.setdefault(str(t), []).append(p.stem)
        moc_text = " ".join(self.graph_bodies.get(p, "") for p in self.mocs)
        clusters = []
        for tag, members in sorted(tag_map.items()):
            if len(members) < MOC_CLUSTER_MIN:
                continue
            in_moc = [m for m in members if f"[[{m}]]" in moc_text or f"concepts/{m}" in moc_text]
            clusters.append({
                "tag": tag, "n": len(members),
                "moc_exists": (self.root / "mocs" / f"{tag}.md").is_file(),
                "n_in_existing_mocs": len(in_moc), "members": members,
            })
        r["moc_cluster_stats"] = clusters

        # stale candidates — a curation OBLIGATION only in repos whose
        # backlog lifecycle is managed (agency: max, cron-drained). In
        # standard repos /discover output is a triage note, not a debt,
        # so report the count as info instead of nagging forever.
        managed = self.budget.get("agency") == "max"
        r["candidates_lifecycle"] = "managed" if managed else "unmanaged"
        cand_dir = self.root / "raw" / "_candidates"
        stale, n_cand = [], 0
        if cand_dir.is_dir():
            for p in sorted(cand_dir.iterdir()):
                if p.is_file():
                    n_cand += 1
                    a = age_days(file_date(p, {},))
                    if managed and a is not None and a > STALE_CANDIDATE_DAYS:
                        stale.append({"path": rel(self.root, p), "age_days": a})
        r["candidates_count"] = n_cand
        r["stale_candidates"] = stale

        r["high_relevance_stale"] = [
            {"path": rel(self.root, p),
             "relevance": self.lit_fm[p].get("relevance"),
             "age_days": age_days(file_date(p, self.lit_fm[p], "added"))}
            for p, e in engaged.items()
            if not e and (self.lit_fm[p].get("relevance") or 0) >= 4
            and (age_days(file_date(p, self.lit_fm[p], "added")) or 0) > STALE_LIT_DAYS
        ]

        if self.mode == "experiments":
            self.experiments_checks(r)
        if self.hce_active:
            self.hce_check(r)
        return r

    def experiments_checks(self, r: dict) -> None:
        prop_dir = self.root / "experiments" / "_proposals"
        stale_p = []
        if prop_dir.is_dir():
            for p in prop_dir.glob("*.md"):
                fm = frontmatter(p)
                if fm.get("status") == "proposed":
                    a = age_days(file_date(p, fm, "date"))
                    if a is not None and a > STALE_PROPOSAL_DAYS:
                        stale_p.append({"path": rel(self.root, p), "age_days": a})
        r["stale_proposals"] = stale_p

        missing_diag, unanchored = [], []
        exp_slugs_done = {d.name for d in self.exp_dirs}
        for d in self.exp_dirs:
            readme = d / "README.md"
            if not readme.is_file():
                missing_diag.append({"path": rel(self.root, d), "reason": "no README"})
                continue
            fm = frontmatter(readme)
            b = body(readme)
            m = re.search(r"^## Diagnostics\s*$(.*?)(?=^## |\Z)", b, re.M | re.S)
            recent_running = fm.get("status") == "running" and (
                (age_days(file_date(readme, fm, "date")) or 99) < 1)
            if not m or re.search(r"intended_effect_confirmed:\s*(<|\s*$)", m.group(1)):
                if not recent_running:
                    missing_diag.append({"path": rel(self.root, readme),
                                         "reason": "missing or placeholder Diagnostics"})
                continue
            for line in m.group(1).splitlines():
                s = line.strip()
                claim = (
                    re.match(r"-\s*intended_effect_confirmed:\s*(yes|partial)", s)
                    or re.match(r"-\s*delta_from_prior:.*\d", s)
                    or (re.match(r"-\s*unexpected_findings:", s)
                        and not re.search(r"none", s, re.I))
                )
                if claim and not ANCHOR_RE.search(s):
                    unanchored.append({"path": rel(self.root, readme), "claim": s[:120]})
        r["missing_diagnostics"] = missing_diag
        r["unanchored_claims"] = unanchored

        # TODO lines the SessionEnd hook appended
        log = self.root / "_meta" / "log.md"
        r["diagnostics_todos"] = [
            ln.strip() for ln in read_or_empty(log).splitlines()
            if "TODO: diagnostics incomplete" in ln
        ]

        # costly sessions without insight
        costly = []
        tl = self.root / "_meta" / "token_log.ndjson"
        sl = self.root / "_meta" / "status.ndjson"
        if tl.is_file():
            sessions: dict[str, dict] = {}
            for ln in tl.read_text(errors="replace").splitlines():
                try:
                    row = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                s = sessions.setdefault(row.get("session_id", "?"),
                                        {"tokens": 0, "ts": []})
                s["tokens"] += sum(int(row.get(k, 0) or 0) for k in
                                   ("input_tokens", "output_tokens", "cache_creation_tokens"))
                if row.get("timestamp"):
                    s["ts"].append(row["timestamp"])
            status_rows = []
            for ln in read_or_empty(sl).splitlines():
                try:
                    status_rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
            flagged_paths = {m["path"] for m in missing_diag}
            for sid, s in sessions.items():
                if s["tokens"] <= COSTLY_SESSION_TOKENS or not s["ts"]:
                    continue
                lo, hi = min(s["ts"]), max(s["ts"])
                touched = {row.get("slug") for row in status_rows
                           if row.get("slug") and lo <= str(row.get("timestamp", "")) <= hi}
                bad = [t for t in touched
                       if any(t in p for p in flagged_paths)]
                if bad or (not touched and s["tokens"] > COSTLY_SESSION_TOKENS):
                    costly.append({"session": sid, "tokens": s["tokens"],
                                   "experiments_missing_diagnostics": sorted(bad)})
        r["costly_sessions_without_insight"] = costly

        # stale expansions
        stale_x = []
        xdir = prop_dir / "_expansions"
        if xdir.is_dir():
            for p in xdir.rglob("*.md"):
                fm = frontmatter(p)
                if fm.get("status") != "proposed":
                    continue
                a = age_days(file_date(p, fm, "date"))
                slug = fm.get("slug", p.stem)
                implemented = any(slug in d for d in exp_slugs_done)
                if a is not None and a > STALE_EXPANSION_DAYS and not implemented:
                    stale_x.append({"path": rel(self.root, p), "age_days": a})
        r["stale_expansions"] = stale_x

        # experiment-loop group linked?
        skills = self.root / ".claude" / "skills"
        linked = skills.exists() and "skills-experiment" in str(
            skills.resolve() if skills.is_symlink() else skills)
        if not linked and skills.is_dir():
            linked = any("skills-experiment" in str(c.resolve())
                         for c in skills.iterdir() if c.is_symlink())
        r["experiment_group_linked"] = bool(linked)

    def hce_check(self, r: dict) -> None:
        violations = []
        for name in ("dvc.lock", "dvc.yaml"):
            f = self.root / name
            if not f.is_file():
                continue
            try:
                data = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError:
                continue
            stages = data.get("stages") or {}
            for stage, spec in (stages.items() if isinstance(stages, dict) else []):
                if stage == "final_eval" or not isinstance(spec, dict):
                    continue
                deps = spec.get("deps") or []
                for dep in deps:
                    path = dep.get("path") if isinstance(dep, dict) else dep
                    if path and ("test/" in str(path) or str(path).startswith("test")):
                        violations.append({"kind": "dvc-dep", "stage": stage,
                                           "dep": str(path), "file": name})
            break  # prefer dvc.lock when present
        tool_re = re.compile(r"\b(Read|Glob|Grep|head|cat|ls|wc)\b[^\n]*\btest/")
        for d in self.exp_dirs:
            log = d / "log.md"
            for i, ln in enumerate(read_or_empty(log).splitlines(), 1):
                if tool_re.search(ln):
                    violations.append({"kind": "tool-log", "file": rel(self.root, log),
                                       "line": i, "text": ln.strip()[:120]})
        r["hce_violations"] = violations


def frontmatter_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def read_or_empty(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def render_text(r: dict) -> str:
    out = [f"MODE: {r['mode']}   (hce_active={str(r['hce_active']).lower()})", ""]

    def section(title, rows, fmt=lambda x: f"  {x}"):
        out.append(f"{title} ({len(rows)})")
        out.extend(fmt(x) for x in rows)
        out.append("")

    section("ORPHANS", r["orphans"])
    section("HIGH-RELEVANCE NO FOLLOWUP", r["high_relevance_no_followup"],
            lambda x: f"  {x['path']}  relevance={x['relevance']}")
    if "in_graph_but_no_experiment" in r:
        section("IN GRAPH BUT NO EXPERIMENT", r["in_graph_but_no_experiment"])
    section("DEAD WIKILINKS", r["dead_wikilinks"],
            lambda x: f"  {x['file']}:{x['line']}  [[{x['target']}]]")
    section("CONCEPTS WITHOUT SOURCES", r["concepts_without_sources"])
    section("MoC CLUSTER STATS", r["moc_cluster_stats"],
            lambda x: f"  tag={x['tag']} n={x['n']} moc_exists={x['moc_exists']} "
                      f"in_mocs={x['n_in_existing_mocs']}")
    if r.get("candidates_lifecycle") == "managed":
        section("STALE CANDIDATES", r["stale_candidates"],
                lambda x: f"  {x['path']}  age={x['age_days']}d")
    elif r.get("candidates_count"):
        out.append(f"CANDIDATES (info): {r['candidates_count']} triage "
                   "file(s) in raw/_candidates/ — no obligation in a "
                   "standard repo; run /curate if and when useful")
        out.append("")
    section("HIGH-RELEVANCE LITERATURE STALE >30d", r["high_relevance_stale"],
            lambda x: f"  {x['path']}  relevance={x['relevance']} age={x['age_days']}d")
    if r["mode"] == "experiments":
        section("STALE PROPOSALS", r["stale_proposals"],
                lambda x: f"  {x['path']}  age={x['age_days']}d")
        section("MISSING DIAGNOSTICS", r["missing_diagnostics"],
                lambda x: f"  {x['path']}  ({x['reason']})")
        section("UNANCHORED CLAIMS", r["unanchored_claims"],
                lambda x: f"  {x['path']}: {x['claim']}")
        section("DIAGNOSTICS TODOS (from _meta/log.md)", r["diagnostics_todos"])
        section("COSTLY SESSIONS WITHOUT INSIGHT", r["costly_sessions_without_insight"],
                lambda x: f"  {x['session']}  {x['tokens']:,} tokens  "
                          f"{x['experiments_missing_diagnostics']}")
        section("STALE EXPANSIONS", r["stale_expansions"],
                lambda x: f"  {x['path']}  age={x['age_days']}d")
        if not r.get("experiment_group_linked"):
            out.append("WARN: dated experiments but no linked experiment-loop skill "
                       "group (see claude-system README, 'Growing a lit repo')")
            out.append("")
    for v in r.get("hce_violations", []):
        out.append(f"HCE VIOLATION (HARD): {v}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = find_root(args.root.resolve())
    if not root:
        print("not inside a project (no ancestor with CLAUDE.md + _meta/)",
              file=sys.stderr)
        return 2
    report = Lint(root).run()
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return 1 if report.get("hce_violations") else 0


if __name__ == "__main__":
    raise SystemExit(main())
