"""Package manager driver for RubyGems (globally installed Ruby gems)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class GemManager(PackageManager):
    """Package manager driver for RubyGems."""

    name: str = "RubyGems"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("gem") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "outdated",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            updates = []
            # Format: "gemname (current < available)"
            import re
            pattern = re.compile(r'^([a-zA-Z0-9_\-]+)\s+\(([^\s]+)\s*<\s*([^\s)]+)\)')
            for line in stdout.decode(errors="ignore").splitlines():
                match = pattern.match(line.strip())
                if match:
                    updates.append({"name": match.group(1), "current": match.group(2), "new": match.group(3)})
            return updates
        except Exception as e:
            raise RuntimeError(f"{self.name} update check failed: {e}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["gem", "update"] + packages
        return ["gem", "update"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "list", "--local",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode != 0:
                return []
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                if line.strip() and "(" in line:
                    installed.append(line.split("(")[0].strip())
            return installed
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["gem", "install", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "search", "--remote", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            results = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line and "(" in line and not line.startswith("*"):
                    name = line.split("(")[0].strip()
                    version = line.split("(")[1].rstrip(")").split(",")[0].strip()
                    results.append({"name": name, "id": name, "description": "", "version": version})
            return results
        except Exception:
            return []
