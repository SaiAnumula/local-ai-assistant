"""Shared helpers for the harness scripts. Standard library only."""

from __future__ import annotations

import json
import os
import pathlib
import urllib.request
from typing import Any

THINK_DELIMITER = "</think>"


def output_dir() -> pathlib.Path:
    """Return $BENCH_OUT_DIR (default results/raw), creating it if needed."""
    path = pathlib.Path(os.environ.get("BENCH_OUT_DIR", "results/raw"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def ollama_url(port: str | int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def get_json(url: str, timeout: float, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def write_json(path: pathlib.Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2))


def final_answer(text: str | None) -> str:
    """Drop any reasoning a model emitted before a closing </think> tag."""
    return (text or "").rsplit(THINK_DELIMITER, 1)[-1].strip()


def short_error(error: Exception, limit: int = 150) -> str:
    return f"{type(error).__name__}: {str(error)[:limit]}"


def read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into {field: KiB}."""
    values = {}
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[1].isdigit():
            values[parts[0].rstrip(":")] = int(parts[1])
    return values


def read_vmstat() -> dict[str, int]:
    values = {}
    for line in pathlib.Path("/proc/vmstat").read_text().splitlines():
        name, value = line.split()
        values[name] = int(value)
    return values


def memory_pressure() -> str:
    return pathlib.Path("/proc/pressure/memory").read_text()


DRM_ROOT = pathlib.Path("/sys/class/drm")


def find_amdgpu_card(drm_root: pathlib.Path = DRM_ROOT) -> pathlib.Path | None:
    """Return the amdgpu device directory to read VRAM from, or None without one.

    $AMDGPU_CARD (for example card0) picks a card by name. Otherwise this uses the card with
    the most VRAM, so a discrete GPU wins over an integrated one whatever order the kernel
    numbered them in.
    """
    card = os.environ.get("AMDGPU_CARD")
    if card:
        device = drm_root / card / "device"
        return device if (device / "mem_info_vram_used").exists() else None

    best, best_total = None, -1
    for used in sorted(drm_root.glob("card[0-9]*/device/mem_info_vram_used")):
        total_file = used.parent / "mem_info_vram_total"
        try:
            total = int(total_file.read_text()) if total_file.exists() else 0
        except (OSError, ValueError):
            continue
        if total > best_total:
            best, best_total = used.parent, total
    return best


def vram_used_bytes(drm_root: pathlib.Path = DRM_ROOT) -> int | None:
    """VRAM in use on the amdgpu card from find_amdgpu_card(), or None without one."""
    device = find_amdgpu_card(drm_root)
    if device is None:
        return None
    try:
        return int((device / "mem_info_vram_used").read_text())
    except (OSError, ValueError):
        return None
