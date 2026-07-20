"""Package manager driver for Julia's Pkg — tracks the default global environment only.

Julia's per-project environments (Project.toml) are out of scope for the same
reason as Bundler/Poetry-project-deps. The default global environment (`@v1.x`)
IS a real, single, trackable package list, so that's what this driver covers.
"""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class JuliaManager(PackageManager):
    name: str = "Julia"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("julia") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "julia", "-e", "using Pkg; for (k,v) in Pkg.dependencies(); println(v.name); end",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            return sorted(set(line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()))
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # Pkg.outdated() output isn't line-parseable in a stable way across
        # Julia versions without significant extra scripting — left empty
        # rather than a brittle parse that breaks on the next Julia release.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            # Keep package names in ARGS rather than interpolating them into Julia source.
            # Blueprint files are user-controlled input and may contain quotes or Julia syntax.
            return ["julia", "-e", "using Pkg; Pkg.update(ARGS)", "--"] + packages
        return ["julia", "-e", "using Pkg; Pkg.update()"]

    def get_install_command(self, package: str) -> list[str]:
        return ["julia", "-e", "using Pkg; Pkg.add(ARGS[1])", "--", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # No official Julia registry search HTTP API — General registry search
        # tools exist as third-party sites only, not a stable programmatic
        # endpoint. Returning [] honestly rather than scraping a webpage.
        return []
