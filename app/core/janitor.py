"""Shared helpers for cleanup targets (orphans, caches, leftover data) reported by drivers."""

import asyncio
import os
from pathlib import Path
from typing import Any


def _walk_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


async def dir_size(path: Path) -> int:
    """Bytes under `path` (0 when it doesn't exist). Unreadable entries are skipped, so a cache
    owned by root can under-report; it never fails."""
    if not path.exists():
        return 0
    return await asyncio.to_thread(_walk_size, path)


def target(
    manager: str, target_id: str, label: str, command: list[str],
    size: int | None = None, items: list[str] | None = None, detail: str = "",
) -> dict[str, Any]:
    """One cleanup target. `size` is bytes freed, or None when it can't be known before running."""
    return {
        "manager": manager, "id": target_id, "label": label, "command": command,
        "bytes": size, "items": items or [], "detail": detail,
    }


def human_size(size: int | None) -> str:
    if size is None:
        return "?"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"
