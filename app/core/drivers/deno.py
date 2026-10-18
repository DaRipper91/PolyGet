"""Package manager driver for Deno (scripts installed with `deno install -g`, plus JSR search)."""

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, fetch_json, register_manager

# Installed script stubs embed their module spec, e.g. "jsr:@std/http@1.0.0/file-server".
_SPEC_RE = re.compile(r"(?:jsr|npm):(@?[\w.\-/]+?)@(\d[\w.\-+]*)")


def _bin_dir() -> Path:
    return Path(os.environ.get("DENO_INSTALL_ROOT", Path.home() / ".deno")) / "bin"


def _read_scripts() -> dict[str, str]:
    """Map each globally installed Deno script to its pinned version ('' when unpinned)."""
    bin_dir = _bin_dir()
    if not bin_dir.is_dir():
        return {}
    scripts = {}
    for path in sorted(bin_dir.iterdir()):
        if not path.is_file() or path.name == "deno":
            continue
        try:
            match = _SPEC_RE.search(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError as e:
            raise DriverError(f"Deno installed-package query failed: {describe_error(e)}") from e
        scripts[path.name] = match.group(2) if match else ""
    return scripts


@register_manager
class DenoManager(PackageManager):
    """Package manager driver for Deno.

    Deno cannot report outdated global scripts, and builds from distro packages ship without
    `deno upgrade`, so this driver lists, installs, and searches JSR but does not offer
    update checks. Callers treat the missing check as "unsupported", not "up to date".
    """

    name: str = "Deno"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("deno") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        return await asyncio.to_thread(_read_scripts)

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Deno cannot report outdated global scripts")

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        raise NotImplementedError("Deno cannot upgrade global scripts or its own runtime portably")

    def get_install_command(self, package: str) -> list[str]:
        return ["deno", "install", "-g", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["deno", "uninstall", "-g"] + packages

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        data = await fetch_json(
            f"https://api.jsr.io/packages?query={query}&limit=20".replace(" ", "%20"),
            label=f"{self.name} JSR search",
        )
        results = []
        for item in data.get("items", []):
            name = f"@{item['scope']}/{item['name']}"
            results.append({
                "name": name, "id": f"jsr:{name}",
                "description": item.get("description", "") or "",
                "version": item.get("latestVersion", "") or "",
            })
        return results
