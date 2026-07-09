"""Package manager driver for pnpm (Node.js, global installs)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class PnpmManager(PackageManager):
    name: str = "pnpm"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("pnpm") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pnpm", "outdated", "--global", "--format", "json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            import json
            data = json.loads(stdout.decode(errors="ignore") or "{}")
            return [{"name": name, "current": info.get("current", ""), "new": info.get("latest", "")}
                    for name, info in data.items()]
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["pnpm", "add", "--global"] + packages
        return ["pnpm", "update", "--global"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pnpm", "list", "--global", "--depth=0", "--json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            import json
            data = json.loads(stdout.decode(errors="ignore") or "[]")
            deps = data[0].get("dependencies", {}) if data else {}
            return list(deps.keys())
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["pnpm", "add", "--global", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Same reasoning as Yarn — pnpm has no native search, shares npm's registry.
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "search", "--json", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": i.get("name", ""), "id": i.get("name", ""),
                     "description": i.get("description", ""), "version": i.get("version", "")}
                    for i in data[:20]] if isinstance(data, list) else []
        except Exception:
            return []
