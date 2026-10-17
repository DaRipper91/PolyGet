"""Package manager driver for Bun (globally installed packages)."""

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote
from packaging.version import InvalidVersion, Version
from app.core.manager import DriverError, PackageManager, describe_error, fetch_json, register_manager


def _global_dir() -> Path:
    return Path(os.environ.get("BUN_INSTALL", Path.home() / ".bun")) / "install" / "global"


def _read_global_versions() -> dict[str, str]:
    """Read globally installed packages straight from Bun's global project on disk.

    `bun pm ls -g` is deliberately avoided: when the global directory does not exist yet it
    silently falls back to the current directory's node_modules and would report an
    unrelated project's packages as global ones.
    """
    root = _global_dir()
    manifest = root / "package.json"
    if not manifest.is_file():
        return {}
    try:
        deps = json.loads(manifest.read_text(encoding="utf-8")).get("dependencies", {})
    except (OSError, ValueError) as e:
        raise DriverError(f"Bun installed-package query failed: {describe_error(e)}") from e
    versions = {}
    for name in deps:
        try:
            pkg = json.loads((root / "node_modules" / name / "package.json").read_text(encoding="utf-8"))
            versions[name] = str(pkg.get("version", ""))
        except (OSError, ValueError):
            versions[name] = ""
    return versions


def _is_newer(latest: str, current: str) -> bool:
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return latest != current


@register_manager
class BunManager(PackageManager):
    """Package manager driver for Bun. Search is left to the NPM driver (same registry)."""

    name: str = "Bun"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("bun") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        return await asyncio.to_thread(_read_global_versions)

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        installed = await self.list_installed_versions()
        if not installed:
            return []

        async def latest(pkg: str) -> str:
            data = await fetch_json(
                f"https://registry.npmjs.org/{quote(pkg, safe='@')}/latest", label=f"{self.name} {pkg} lookup"
            )
            return str(data["version"])

        results = await asyncio.gather(*(latest(p) for p in installed), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures and len(failures) == len(results):
            raise DriverError(f"{self.name} update check failed: {failures[0]}")
        return [
            {"name": pkg, "current": cur, "new": new}
            for (pkg, cur), new in zip(installed.items(), results)
            if not isinstance(new, Exception) and cur and _is_newer(new, cur)
        ]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return ["bun", "update", "-g"] + (packages or [])

    def get_install_command(self, package: str) -> list[str]:
        return ["bun", "add", "-g", package]

    def get_remove_command(self, package: str) -> list[str]:
        return ["bun", "remove", "-g", package]
