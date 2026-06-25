"""Service & port registry reader for the dashboard.

Reads ~/claude-system/registry/services.yaml (the single source of truth) and
live-probes each concrete port so the /ports page shows what's actually up.
"""
from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import yaml

from .cache import ttl_cache

_REGISTRY = Path(__file__).resolve().parents[2] / "registry" / "services.yaml"


def _port_up(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@ttl_cache(seconds=10)
def registry() -> dict[str, Any]:
    if not _REGISTRY.exists():
        return {"blocks": [], "services": [], "extra_projects": []}
    try:
        data = yaml.safe_load(_REGISTRY.read_text()) or {}
    except yaml.YAMLError:
        return {"blocks": [], "services": [], "extra_projects": []}
    services = []
    for s in data.get("services", []) or []:
        port = s.get("port")
        is_range = isinstance(port, str) and "-" in port
        status = "reserved" if is_range else ("up" if _port_up(int(port)) else "down")
        services.append({**s, "is_range": is_range, "status": status})
    # Stable sort by first port number.
    def _key(s):
        p = s.get("port")
        return int(str(p).split("-")[0]) if p is not None else 0
    services.sort(key=_key)
    return {
        "host": data.get("host", ""),
        "tailscale_ip": data.get("tailscale_ip", ""),
        "lan_ip": data.get("lan_ip", ""),
        "blocks": data.get("blocks", []) or [],
        "services": services,
        "extra_projects": data.get("extra_projects", []) or [],
        "path": str(_REGISTRY),
    }


def extra_projects() -> list[dict]:
    return registry().get("extra_projects", [])
