"""Append-only JSON Lines log of upgrade attempts."""

import json
import threading
import time
from pathlib import Path
from typing import Any

_HISTORY_PATH = Path.home() / ".local" / "share" / "polyget" / "history.jsonl"

# Serialize writes to history.jsonl so concurrent GUI + CLI (or two GUI
# instances) can't interleave partial writes or corrupt JSONL lines.
_save_lock = threading.Lock()


def record_upgrade(
    manager_name: str,
    packages: list[str],
    success: bool,
    path: Path = _HISTORY_PATH,
    not_upgraded: list[str] | None = None,
) -> None:
    """Log one upgrade run. `not_upgraded` lists packages still outdated after a run that
    exited 0; any such package makes the run a failure, since the tool claimed success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "manager": manager_name,
        "packages": packages,
        "success": success and not not_upgraded,
    }
    if not_upgraded:
        entry["not_upgraded"] = not_upgraded
    with path.open("a", encoding="utf-8") as f:
        with _save_lock:
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
