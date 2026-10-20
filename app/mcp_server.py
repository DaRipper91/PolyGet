"""Model Context Protocol (MCP) server for PolyGet.

Exposes PolyGet's multi-package-manager inspection, search, audit, and upgrade
capabilities to AI agents (such as Antigravity/agy, Claude, Gemini).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is in sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp.server.mcpserver import MCPServer

from app.core.history_store import load_history
from app.core.manager import (
    DriverError,
    PackageManager,
    describe_error,
    discover_managers,
    get_all_managers,
)
from app.core.restart import check_restart_needed
from app.cli import (
    _gather_per_manager,
    _scan_outdated,
    _select_managers,
    _with_hooks,
)


def create_server() -> MCPServer:
    """Create and configure the PolyGet MCPServer instance."""
    server = MCPServer("polyget")

    @server.tool()
    async def polyget_list_managers(all: bool = False) -> list[dict[str, Any]]:
        """List detected package managers on this system and their availability status.

        Args:
            all: If True, include unsupported/uninstalled package managers from the catalog.
        """
        managers = get_all_managers() if all else discover_managers()
        return [
            {
                "name": m.name,
                "category": m.category,
                "available": m.is_available(),
                "supports_repos": m.supports_repos,
            }
            for m in managers
        ]

    @server.tool()
    async def polyget_check_outdated(
        manager: str | None = None,
        include_ignored: bool = False,
    ) -> dict[str, Any]:
        """Check for outdated packages across all available managers or a specific manager.

        Args:
            manager: Specific manager name (e.g. 'dnf', 'cargo', 'npm'). If None, checks all.
            include_ignored: If True, includes packages the user marked as ignored.
        """
        managers = _select_managers([manager] if manager else None)
        results, rows = await _scan_outdated(managers, include_ignored)
        return {
            "updates": rows,
            "managers": {
                n: (
                    {"ok": True, "count": len(r["result"])}
                    if r["ok"]
                    else {
                        "ok": False,
                        "error": r["error"],
                        **({"unsupported": True} if r.get("unsupported") else {}),
                    }
                )
                for n, r in results.items()
            },
        }

    @server.tool()
    async def polyget_list_installed(manager: str | None = None) -> dict[str, Any]:
        """List currently installed packages for a specific manager or all available managers.

        Args:
            manager: Specific manager name (e.g. 'dnf', 'pipx', 'flatpak'). If None, checks all.
        """
        managers = _select_managers([manager] if manager else None)
        results = await _gather_per_manager(managers, "list_installed")
        return {
            n: (r["result"] if r["ok"] else {"error": r["error"]})
            for n, r in results.items()
        }

    @server.tool()
    async def polyget_search(
        query: str,
        manager: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search packages across package managers.

        Args:
            query: Package name or search keyword.
            manager: Specific manager to search (e.g. 'dnf', 'flatpak', 'npm'). If None, searches all.
            limit: Maximum number of results per manager.
        """
        managers = _select_managers([manager] if manager else None)
        results = await _gather_per_manager(managers, "search_packages", query)
        rows: list[dict[str, Any]] = []
        for name, res in results.items():
            if res["ok"]:
                rows.extend(
                    {"manager": name, **pkg} for pkg in res["result"][:limit]
                )
        failed = {
            n: r["error"]
            for n, r in results.items()
            if not r["ok"] and not r.get("unsupported")
        }
        unsupported = sorted(
            n for n, r in results.items() if r.get("unsupported")
        )
        return {
            "results": rows,
            "errors": failed,
            "unsupported": unsupported,
        }

    @server.tool()
    async def polyget_audit(manager: str | None = None) -> dict[str, Any]:
        """Audit packages for security vulnerabilities across supported managers (npm, cargo, pip).

        Args:
            manager: Specific manager to audit. If None, audits all supporting managers.
        """
        managers = _select_managers([manager] if manager else None)
        results = await _gather_per_manager(managers, "check_vulnerabilities")
        rows = [
            {"manager": n, **v}
            for n, r in results.items()
            if r["ok"]
            for v in r["result"]
        ]
        errors = {
            n: r["error"]
            for n, r in results.items()
            if not r["ok"] and not r.get("unsupported")
        }
        return {
            "vulnerabilities": rows,
            "errors": errors,
        }

    @server.tool()
    async def polyget_list_repos(manager: str | None = None) -> list[dict[str, Any]]:
        """List configured repositories/remotes for managers that support them (DNF, Flatpak, APT).

        Args:
            manager: Specific manager to inspect. If None, lists across all repo-capable managers.
        """
        managers = [
            m
            for m in _select_managers([manager] if manager else None)
            if m.supports_repos
        ]
        results = await _gather_per_manager(managers, "list_repos")
        return [
            {"manager": n, **repo}
            for n, r in results.items()
            if r["ok"]
            for repo in r["result"]
        ]

    @server.tool()
    async def polyget_needs_restart() -> dict[str, Any]:
        """Check if system services or a system reboot is required after recent updates."""
        return await check_restart_needed()

    @server.tool()
    async def polyget_upgrade_plan(
        manager: str | None = None,
        packages: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate an upgrade execution plan without running any commands (dry-run).

        Returns the exact command lines that would be run for each manager.

        Args:
            manager: Specific manager to target. Required if specific packages are given.
            packages: Specific package names to upgrade. If None, targets all outdated packages.
        """
        if packages and not manager:
            raise ValueError("Naming specific packages requires specifying a manager.")

        managers = _select_managers([manager] if manager else None)

        if packages:
            targets = {managers[0].name: list(packages)}
        else:
            results, rows = await _scan_outdated(managers, include_ignored=False)
            targets = {}
            for row in rows:
                targets.setdefault(row["manager"], []).append(row["name"])

        by_name = {m.name: m for m in managers}
        steps = []
        for name, pkgs in targets.items():
            try:
                command = by_name[name].get_upgrade_command(pkgs)
                steps.append({"manager": name, "packages": pkgs, "command": command})
            except (NotImplementedError, DriverError) as e:
                steps.append(
                    {
                        "manager": name,
                        "packages": pkgs,
                        "error": describe_error(e),
                    }
                )

        return {"executed": False, "steps": _with_hooks(steps, "upgrade")}

    @server.tool()
    async def polyget_history(limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve recent upgrade and removal history recorded by PolyGet.

        Args:
            limit: Maximum history records to return.
        """
        return load_history(limit=limit)

    return server


def run_server() -> None:
    """Run the PolyGet MCP server in stdio transport mode."""
    # Ensure stdout is clean for JSON-RPC; redirect any unintended prints to stderr
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    run_server()
