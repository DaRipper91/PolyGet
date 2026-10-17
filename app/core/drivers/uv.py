"""Package manager driver for uv (Python tools installed with `uv tool install`)."""

import asyncio
import shutil
from typing import Any
from packaging.version import InvalidVersion, Version
from app.core.manager import DriverError, PackageManager, fetch_json, register_manager, run_capture


def _is_newer(latest: str, current: str) -> bool:
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return latest != current


@register_manager
class UvManager(PackageManager):
    """Package manager driver for uv tools.

    uv has no `outdated` or `search` command for tools, so updates are checked against
    PyPI directly. Search is left unsupported on purpose: the Pipx driver already searches
    PyPI, and a second copy of the same results would only add noise.
    """

    name: str = "uv"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("uv") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        out = await run_capture(["uv", "tool", "list"], label=f"{self.name} installed-package query")
        versions = {}
        for line in out.splitlines():
            parts = line.split()
            # "agentdeck v0.1.0" per tool; its executables follow as "- agentdeck".
            if len(parts) == 2 and not line.startswith("-") and parts[1].startswith("v"):
                versions[parts[0]] = parts[1][1:]
        return versions

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        tools = await self.list_installed_versions()
        if not tools:
            return []

        async def latest(tool: str) -> str:
            data = await fetch_json(f"https://pypi.org/pypi/{tool}/json", label=f"{self.name} {tool} lookup")
            return str(data["info"]["version"])

        results = await asyncio.gather(*(latest(t) for t in tools), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        # One flaky lookup must not hide the rest, but if every lookup died the registry is
        # unreachable and "no updates" would be a false clean bill.
        if failures and len(failures) == len(results):
            raise DriverError(f"{self.name} update check failed: {failures[0]}")
        return [
            {"name": tool, "current": current, "new": new}
            for (tool, current), new in zip(tools.items(), results)
            if not isinstance(new, Exception) and _is_newer(new, current)
        ]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["uv", "tool", "upgrade"] + packages
        return ["uv", "tool", "upgrade", "--all"]

    def get_install_command(self, package: str) -> list[str]:
        return ["uv", "tool", "install", package]
