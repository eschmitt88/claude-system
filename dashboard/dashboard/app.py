"""FastAPI entry point. Three views: /, /queue, /project/<name>."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from coordinator.readers import (
    latest_hardware_sample,
    queued_jobs,
    recent_completed_jobs,
    tokens_in_last,
)

from .projects import list_projects, project_cycles, project_inbox_count

BASE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="claude-system dashboard")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _tmux_loops() -> list[dict]:
    """List tmux sessions whose name starts with 'loop' — convention."""
    if not shutil.which("tmux"):
        return []
    try:
        out = subprocess.check_output(
            ["tmux", "list-sessions", "-F", "#{session_name}|#{session_created}|#{session_attached}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
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


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    hw = latest_hardware_sample()
    tokens_5h = tokens_in_last(5 * 3600)
    tokens_7d = tokens_in_last(7 * 24 * 3600)
    loops = _tmux_loops()
    return TEMPLATES.TemplateResponse(
        request,
        "home.html",
        {
            "hw": hw,
            "tokens_5h": tokens_5h,
            "tokens_7d": tokens_7d,
            "loops": loops,
        },
    )


@app.get("/queue", response_class=HTMLResponse)
async def queue(request: Request):
    running_and_queued = queued_jobs(limit=50)
    completed = recent_completed_jobs(limit=25)
    return TEMPLATES.TemplateResponse(
        request,
        "queue.html",
        {"jobs": running_and_queued, "completed": completed},
    )


@app.get("/project/{name}", response_class=HTMLResponse)
async def project(request: Request, name: str):
    cycles = project_cycles(name, limit=10)
    inbox = project_inbox_count(name)
    tokens_7d = tokens_in_last(7 * 24 * 3600, project=name)
    diag = None
    # Surface the latest experiment's Diagnostics if we can.
    if cycles and cycles[0].get("diagnostics"):
        diag = cycles[0]["diagnostics"]
    return TEMPLATES.TemplateResponse(
        request,
        "project.html",
        {
            "project": name,
            "cycles": cycles,
            "inbox": inbox,
            "tokens_7d": tokens_7d,
            "diagnostics": diag,
        },
    )


@app.get("/api/home.json")
async def home_json():
    hw = latest_hardware_sample()
    return {
        "hw": hw,
        "tokens_5h": tokens_in_last(5 * 3600),
        "tokens_7d": tokens_in_last(7 * 24 * 3600),
        "loops": _tmux_loops(),
    }


@app.get("/api/projects.json")
async def projects_json():
    return {"projects": list_projects()}


@app.get("/events")
async def events(request: Request):
    """SSE stream: a snapshot every 5s."""

    async def gen():
        while True:
            if await request.is_disconnected():
                break
            payload = {
                "hw": latest_hardware_sample(),
                "tokens_5h": tokens_in_last(5 * 3600),
                "loops": _tmux_loops(),
            }
            yield {"event": "snapshot", "data": json.dumps(payload, default=str)}
            await asyncio.sleep(5)

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
