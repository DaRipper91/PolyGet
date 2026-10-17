"""Package manager driver for Bundler (Ruby gems in tracked project directories)."""

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any
from app.core.manager import DriverError, PackageManager, register_manager, run_capture
from app.core.projects import make_target, resolve_single_project, tracked_projects

_OUTDATED_RE = re.compile(r"^(\S+) \(newest ([^,)]+), installed ([^,)]+)")
_LIST_RE = re.compile(r"^\s+\*\s+(\S+) \(([^)]+)\)")


@register_manager
class BundlerManager(PackageManager):
    """Package manager driver for Bundler.

    Bundler has no global package list, so it scans the project directories registered with
    `polyget projects add` (those containing a Gemfile). It only reports as available once
    at least one exists, so an unconfigured install shows nothing rather than a false
    "all up to date".
    """

    name: str = "Bundler"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("bundle") is not None and bool(tracked_projects("Gemfile"))

    async def check_updates(self) -> list[dict[str, Any]]:
        async def scan(project: Path) -> list[dict[str, Any]]:
            # `bundle outdated` exits 1 when something is outdated.
            out = await run_capture(
                ["bundle", "outdated", "--parseable"], cwd=project, timeout=60.0, ok_codes=(0, 1),
                label=f"{self.name} update check in {project}",
            )
            updates = []
            for line in out.splitlines():
                match = _OUTDATED_RE.match(line.strip())
                if match:
                    updates.append({
                        "name": make_target(match.group(1), project),
                        "current": match.group(3), "new": match.group(2),
                    })
            return updates

        projects = tracked_projects("Gemfile")
        results = await asyncio.gather(*(scan(p) for p in projects), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures and len(failures) == len(results):
            raise DriverError(str(failures[0]))
        return [u for r in results if not isinstance(r, Exception) for u in r]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        project, gems = resolve_single_project(packages, "Gemfile", self.name)
        # BUNDLE_GEMFILE selects the project without needing a working directory.
        return ["env", f"BUNDLE_GEMFILE={project / 'Gemfile'}", "bundle", "update"] + gems

    async def list_installed_versions(self) -> dict[str, str]:
        async def scan(project: Path) -> str:
            return await run_capture(
                ["bundle", "list"], cwd=project, timeout=30.0, label=f"{self.name} installed-package query in {project}"
            )

        projects = tracked_projects("Gemfile")
        results = await asyncio.gather(*(scan(p) for p in projects), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures and len(failures) == len(results):
            raise DriverError(str(failures[0]))
        versions: dict[str, str] = {}
        for out in (r for r in results if not isinstance(r, Exception)):
            for line in out.splitlines():
                match = _LIST_RE.match(line)
                if match:
                    versions.setdefault(match.group(1), match.group(2))
        return versions

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())
