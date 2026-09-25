"""Append-only JSON Lines log of upgrade attempts."""

import json
import time
from pathlib import Path
from typing import Any

_HISTORY_PATH = Path.home() / ".local" / "share" / "polyget" / "history.jsonl"


def record_upgrade(manager_name: str, packages: list[str], success: bool, path: Path = _HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "manager": manager_name,
        "packages": packages,
        "success": success,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def load_history(path: Path = _HISTORY_PATH, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(records))
