"""FastAPI entry point.

Design notes (perf):
- Page handlers are sync `def`. FastAPI runs them in its threadpool, so any
  blocking sqlite or filesystem I/O does NOT freeze the event loop.
- The SSE stream pulls from a single shared snapshot updated by one
  background task — N connected clients = 1 producer, not N.
- Hot filesystem reads are TTL-cached in `cache.py`.
- GZip middleware is on for everything.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from coordinator import ccusage
from coordinator.readers import latest_hardware_sample, tokens_in_last

from .projects import (
    all_project_status,
    build_attention_feed,
    list_candidates,
    list_concepts,
    list_literature,
    list_projects,
    project_activity,
    project_cycles,
    project_dashboard_dir,
    project_status,
    read_concept,
    read_experiment,
    read_literature_note,
    search_all,
    snippet_for_concept,
    snippet_for_literature,
    tokens_per_day,
)
from .ports import registry as ports_registry, extra_projects

BASE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="claude-system dashboard")
app.add_middleware(GZipMiddleware, minimum_size=512)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.middleware("http")
async def _static_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# === shared snapshot for SSE ================================================
#
# A single background task maintains _snapshot. All SSE clients read from it,
# so we never run the underlying sync I/O once-per-client-per-tick.

_snapshot: dict = {
    "hw": None,
    "tokens_5h": None,
    "loops": [],
    "ccusage_block": None,
    "ccusage_7d": None,
}
_snapshot_seq: int = 0


async def _tmux_loops_async() -> list[dict]:
    """Async tmux probe — never blocks the event loop."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "list-sessions",
            "-F", "#{session_name}|#{session_created}|#{session_attached}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            return []
    except FileNotFoundError:
        return []
    out = stdout.decode("utf-8", errors="replace")
    sessions = []
    for line in out.strip().splitlines():
        if not line:
            continue
        name, created, attached = (line.split("|") + ["", "", ""])[:3]
        if name.startswith("loop") or "claude" in name.lower():
            sessions.append(
                {"name": name, "created": created, "attached": attached == "1"}
            )
    return sessions


async def _refresh_snapshot() -> None:
    """Update _snapshot in-place. Sync calls go through to_thread.

    ccusage subprocesses (~0.4s each) run via to_thread so they don't block
    the event loop. If either fails/times-out the relevant field stays None
    and the template degrades gracefully.
    """
    global _snapshot, _snapshot_seq
    hw, tk5, cc_block, cc_7d = await asyncio.gather(
        asyncio.to_thread(latest_hardware_sample),
        asyncio.to_thread(tokens_in_last, 5 * 3600),
        asyncio.to_thread(ccusage.active_block),
        asyncio.to_thread(ccusage.weekly_anchored),
    )
    loops = await _tmux_loops_async()
    _snapshot = {
        "hw": hw,
        "tokens_5h": tk5,
        "loops": loops,
        "ccusage_block": cc_block,
        "ccusage_7d": cc_7d,
    }
    _snapshot_seq += 1


async def _snapshot_producer() -> None:
    """One global task. Updates _snapshot every 5s for as long as the app runs."""
    while True:
        try:
            await _refresh_snapshot()
        except Exception:
            pass  # transient — try again next tick
        await asyncio.sleep(5)


@app.on_event("startup")
async def _on_startup():
    # Prime once so the first page render has data.
    try:
        await _refresh_snapshot()
    except Exception:
        pass
    asyncio.create_task(_snapshot_producer())


# === template helpers =======================================================


def _ctx(extra: dict) -> dict:
    """Every TemplateResponse needs `projects` for the nav and `live` for the strip."""
    return {"projects": list_projects(), "live": _snapshot, **extra}


# === pages (sync def — FastAPI runs in threadpool) ==========================


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Pull ccusage + hw straight from the shared snapshot — the producer
    # refreshes every 5s and we don't want to fan out subprocess calls per
    # request. tokens_in_last is cheap (sqlite) so still computed live.
    hw = _snapshot.get("hw") or latest_hardware_sample()
    tokens_5h = tokens_in_last(5 * 3600)
    tokens_7d = tokens_in_last(7 * 24 * 3600)
    project_rollup = all_project_status()
    return TEMPLATES.TemplateResponse(
        request,
        "home.html",
        _ctx(
            {
                "active": "home",
                "hw": hw,
                "tokens_5h": tokens_5h,
                "tokens_7d": tokens_7d,
                "cc_block": _snapshot.get("ccusage_block"),
                "cc_7d": _snapshot.get("ccusage_7d"),
                "loops": _snapshot.get("loops") or [],
                "project_rollup": project_rollup,
                "attention": build_attention_feed(project_rollup),
            }
        ),
    )


@app.get("/projects-hub", response_class=HTMLResponse)
def projects_hub(request: Request):
    """Lists every research project with its dashboard status (if any), plus
    external (non-research) projects from the service registry."""
    from .ports import _port_up
    projects = list_projects()
    rollup = {p["name"]: p for p in all_project_status()}
    rows = []
    for p in projects:
        st = rollup.get(p["name"], {})
        dash = p.get("dashboard")
        # Live-probe server-kind dashboards so the hub reflects reality.
        if dash and dash.get("kind") == "server" and isinstance(dash.get("port"), int):
            dash["live"] = _port_up(dash["port"])
        rows.append({**p, "status": st})
    return TEMPLATES.TemplateResponse(
        request,
        "projects_hub.html",
        _ctx({"active": "projects", "rows": rows,
              "external": extra_projects()}),
    )


@app.get("/ports", response_class=HTMLResponse)
def ports(request: Request):
    """Service & port registry with live status."""
    return TEMPLATES.TemplateResponse(
        request,
        "ports.html",
        _ctx({"active": "ports", "reg": ports_registry()}),
    )


@app.get("/projects/{name}/dashboard")
def project_dashboard_root(name: str):
    """Redirect /projects/<n>/dashboard → /projects/<n>/dashboard/ for the index."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/projects/{name}/dashboard/", status_code=307)


@app.get("/projects/{name}/dashboard/")
def project_dashboard_index(name: str):
    """Serve the dashboard's entry file (index.html by default)."""
    from fastapi.responses import FileResponse
    d = project_dashboard_dir(name)
    if d is None:
        return HTMLResponse(f"no dashboard for {name}", status_code=404)
    entry = d / "index.html"
    if not entry.exists():
        return HTMLResponse(f"dashboard entry not found at {entry}", status_code=404)
    return FileResponse(str(entry))


@app.get("/projects/{name}/dashboard/{filepath:path}")
def project_dashboard_file(name: str, filepath: str):
    """Serve any asset inside the project's dashboard/ directory."""
    from fastapi.responses import FileResponse
    d = project_dashboard_dir(name)
    if d is None:
        return HTMLResponse(f"no dashboard for {name}", status_code=404)
    target = (d / filepath).resolve()
    # Path-traversal guard
    try:
        target.relative_to(d.resolve())
    except ValueError:
        return HTMLResponse("forbidden", status_code=403)
    if not target.exists() or not target.is_file():
        return HTMLResponse(f"not found: {filepath}", status_code=404)
    return FileResponse(str(target))


@app.get("/project/{name}", response_class=HTMLResponse)
def project(request: Request, name: str):
    cycles = project_cycles(name, limit=10)
    status = project_status(name)
    tokens_7d = tokens_in_last(7 * 24 * 3600, project=name)
    diag = cycles[0]["diagnostics"] if cycles and cycles[0].get("diagnostics") else None
    return TEMPLATES.TemplateResponse(
        request,
        "project.html",
        _ctx(
            {
                "active": "overview",
                "project": name,
                "cycles": cycles,
                "status": status,
                "tokens_7d": tokens_7d,
                "diagnostics": diag,
            }
        ),
    )


@app.get("/project/{name}/activity", response_class=HTMLResponse)
def project_activity_view(request: Request, name: str):
    return TEMPLATES.TemplateResponse(
        request,
        "activity.html",
        _ctx({"active": "activity", "project": name, **project_activity(name)}),
    )


@app.get("/project/{name}/candidates", response_class=HTMLResponse)
def project_candidates(request: Request, name: str):
    return TEMPLATES.TemplateResponse(
        request,
        "candidates.html",
        _ctx({"active": "candidates", "project": name, "files": list_candidates(name)}),
    )


@app.get("/project/{name}/literature", response_class=HTMLResponse)
def project_literature(request: Request, name: str):
    return TEMPLATES.TemplateResponse(
        request,
        "literature_index.html",
        _ctx({"active": "literature", "project": name, "groups": list_literature(name)}),
    )


@app.get("/project/{name}/literature/{relpath:path}", response_class=HTMLResponse)
def project_literature_note(request: Request, name: str, relpath: str):
    note = read_literature_note(name, relpath)
    if note is None:
        return HTMLResponse("note not found", status_code=404)
    return TEMPLATES.TemplateResponse(
        request,
        "literature_note.html",
        _ctx({"active": "literature", "project": name, "note": note}),
    )


@app.get("/project/{name}/experiment/{slug}", response_class=HTMLResponse)
def project_experiment(request: Request, name: str, slug: str):
    exp = read_experiment(name, slug)
    if exp is None:
        return HTMLResponse("experiment not found", status_code=404)
    return TEMPLATES.TemplateResponse(
        request,
        "experiment.html",
        _ctx({"active": "overview", "project": name, "exp": exp}),
    )


@app.get("/project/{name}/concepts", response_class=HTMLResponse)
def project_concepts(request: Request, name: str):
    return TEMPLATES.TemplateResponse(
        request,
        "concepts_index.html",
        _ctx({"active": "concepts", "project": name, "concepts": list_concepts(name)}),
    )


@app.get("/project/{name}/concepts/{slug}", response_class=HTMLResponse)
def project_concept(request: Request, name: str, slug: str):
    concept = read_concept(name, slug)
    if concept is None:
        return HTMLResponse("concept not found", status_code=404)
    return TEMPLATES.TemplateResponse(
        request,
        "concept.html",
        _ctx({"active": "concepts", "project": name, "concept": concept}),
    )


# === JSON / API endpoints (also sync def) ===================================


@app.get("/api/home.json")
def home_json():
    # Cheap: read straight from the shared snapshot.
    return _snapshot


@app.get("/api/projects.json")
def projects_json():
    return {"projects": list_projects()}


@app.get("/api/projects/status.json")
def projects_status_json():
    return {"projects": all_project_status()}


@app.get("/api/search")
def api_search(q: str = ""):
    return {"results": search_all(q, limit=20) if q.strip() else []}


@app.get("/api/preview/concepts/{project}/{slug}")
def api_preview_concept(project: str, slug: str):
    snip = snippet_for_concept(project, slug)
    if snip is None:
        return HTMLResponse("not found", status_code=404)
    return {"kind": "concept", "where": f"{project}/concepts/{slug}", "snippet": snip}


@app.get("/api/preview/literature/{project}/{relpath:path}")
def api_preview_literature(project: str, relpath: str):
    snip = snippet_for_literature(project, relpath)
    if snip is None:
        return HTMLResponse("not found", status_code=404)
    return {"kind": "literature", "where": f"{project}/{relpath}", "snippet": snip}


@app.get("/api/tokens/sparkline")
def api_tokens_sparkline():
    return {"points": tokens_per_day(days=7)}


# === SSE: stream the shared snapshot, not per-client work ==================


@app.get("/events")
async def events(request: Request):
    """Pure-async — only reads the in-memory snapshot. Never blocks."""
    last_seq = -1

    async def gen():
        nonlocal last_seq
        while True:
            if await request.is_disconnected():
                break
            global _snapshot_seq
            if _snapshot_seq != last_seq:
                last_seq = _snapshot_seq
                yield {"event": "snapshot", "data": json.dumps(_snapshot, default=str)}
            await asyncio.sleep(2)

    return EventSourceResponse(gen())


def run():
    import uvicorn

    host, _, port = os.environ.get("CLAUDE_DASHBOARD_BIND", "0.0.0.0:8080").partition(":")
    uvicorn.run(
        "dashboard.app:app",
        host=host or "0.0.0.0",
        port=int(port or "8080"),
        log_level="info",
    )
