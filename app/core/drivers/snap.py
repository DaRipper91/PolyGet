"""Package manager driver for Snap (Canonical's universal packages)."""

import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager, run_capture


@register_manager
class SnapManager(PackageManager):
    """Package manager driver for snapd."""

    name: str = "Snap"
    category: str = "Universal"

    def is_available(self) -> bool:
        return shutil.which("snap") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        out = await run_capture(["snap", "list"], label=f"{self.name} installed-package query")
        versions = {}
        # Table with a "Name Version Rev Tracking Publisher Notes" header row.
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                versions[parts[0]] = parts[1]
        return versions

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        installed = await self.list_installed_versions()
        # Prints a "Name Version Rev Size Publisher Notes" table of pending refreshes, and
        # nothing on stdout (a notice on stderr) when everything is current.
        out = await run_capture(["snap", "refresh", "--list"], label=f"{self.name} update check", timeout=30.0)
        updates = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                updates.append({"name": parts[0], "current": installed.get(parts[0], "?"), "new": parts[1]})
        return updates

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return ["pkexec", "snap", "refresh"] + (packages or [])

    def get_install_command(self, package: str) -> list[str]:
        return ["pkexec", "snap", "install", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        out = await run_capture(["snap", "find", query], label=f"{self.name} search", timeout=20.0)
        results = []
        # Columns: Name Version Publisher Notes Summary (summary is free text).
        for line in out.splitlines()[1:]:
            parts = line.split(None, 4)
            if len(parts) >= 2:
                results.append({
                    "name": parts[0], "id": parts[0], "version": parts[1],
                    "description": parts[4] if len(parts) == 5 else "",
                })
        return results
