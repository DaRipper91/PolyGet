"""Package manager driver for Yarn (Node.js, global installs)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class YarnManager(PackageManager):
    name: str = "Yarn"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("yarn") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "yarn", "global", "outdated", "--json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            import json
            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "table":
                    for row in obj.get("data", {}).get("body", []):
                        if len(row) >= 4:
                            updates.append({"name": row[0], "current": row[1], "new": row[3]})
            return updates
        except Exception as e:
            raise RuntimeError(f"{self.name} update check failed: {e}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["yarn", "global", "add"] + packages
        return ["yarn", "global", "upgrade"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "yarn", "global", "list", "--depth=0",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("info") or "@" not in line:
                    continue
                # Format: '- packagename@version'
                name = line.lstrip("- ").rsplit("@", 1)[0]
                if name:
                    installed.append(name)
            return installed
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["yarn", "global", "add", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Yarn Classic has no built-in search command; it shares npm's registry,
        # so delegate to the npm registry search API directly rather than
        # reinventing it — same registry, same package names.
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
