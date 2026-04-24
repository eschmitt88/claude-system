"""Hardware poller. One-shot sampling; run on a systemd timer at 30s cadence.

Writes one row to hardware_samples and prunes rows older than 7 days on
every invocation. NVIDIA GPU sampling uses pynvml; missing GPU is
tolerated (fields come back as None).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import psutil

from .db import prune_hardware_samples
from .writers import insert_hardware_sample


def _sample_gpu() -> dict:
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        try:
            if pynvml.nvmlDeviceGetCount() == 0:
                return {}
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0  # mW → W
            except pynvml.NVMLError:
                power = None
            return {
                "gpu_util_pct": float(util.gpu),
                "gpu_mem_used_gb": mem.used / (1024**3),
                "gpu_mem_total_gb": mem.total / (1024**3),
                "gpu_temp_c": float(temp),
                "gpu_power_w": power,
            }
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return {}


def _sample_disk(path: str = "/mnt/projects") -> dict:
    p = Path(path)
    if not p.exists():
        p = Path.home()
    du = shutil.disk_usage(str(p))
    return {
        "disk_used_gb": (du.total - du.free) / (1024**3),
        "disk_free_gb": du.free / (1024**3),
    }


def sample_once() -> dict:
    vm = psutil.virtual_memory()
    out = {
        "cpu_percent": psutil.cpu_percent(interval=1.0),
        "ram_percent": vm.percent,
        "ram_used_gb": vm.used / (1024**3),
        "ram_total_gb": vm.total / (1024**3),
    }
    out.update(_sample_disk())
    out.update(_sample_gpu())
    return out


def main() -> int:
    sample = sample_once()
    insert_hardware_sample(sample)
    # Idempotent pruning; cheap.
    prune_hardware_samples(keep_days=7)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
