"""Persisted per-package ignore list, keyed by manager name + package name."""

import json
from pathlib import Path

_IGNORE_PATH = Path.home() / ".config" / "polyget" / "ignored_packages.json"


class IgnoreStore:
    """Simple JSON-backed set of (manager_name, package_name) pairs to exclude from auto-select."""

    def __init__(self, path: Path = _IGNORE_PATH) -> None:
        self._path = path
        self._entries: set[tuple[str, str]] = self._load()

    def _load(self) -> set[tuple[str, str]]:
        if not self._path.exists():
            return set()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {(item["manager"], item["package"]) for item in data}
        except Exception:
            return set()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"manager": m, "package": p} for m, p in sorted(self._entries)]
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def is_ignored(self, manager_name: str, package_name: str) -> bool:
        return (manager_name, package_name) in self._entries

    def add(self, manager_name: str, package_name: str) -> None:
        self._entries.add((manager_name, package_name))
        self._save()

    def remove(self, manager_name: str, package_name: str) -> None:
        self._entries.discard((manager_name, package_name))
        self._save()

    def all_entries(self) -> list[tuple[str, str]]:
        return sorted(self._entries)
