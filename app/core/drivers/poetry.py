"""Package manager driver for Poetry — tracks Poetry's own global plugins only.

Poetry's actual dependency management (pyproject.toml/poetry.lock) is inherently
per-project, same reasoning as Bundler (see taxonomy plan Section 0). What IS
global and trackable is `poetry self` — the plugins installed into Poetry's own
environment. That's the scope of this driver; it deliberately does not attempt
to surface arbitrary project dependencies.
"""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class PoetryManager(PackageManager):
    name: str = "Poetry"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("poetry") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "poetry", "self", "show",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.split()
                if parts and parts[0] and not line.startswith(" "):
                    installed.append(parts[0])
            return installed
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        return []  # no bulk outdated-check for self plugins; low churn, low value to fake

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["poetry", "self", "update"] + packages
        return ["poetry", "self", "update"]

    def get_install_command(self, package: str) -> list[str]:
        return ["poetry", "self", "add", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Poetry plugins are just PyPI packages tagged appropriately — reuse
        # the same local-index approach as pipx.py rather than duplicating it.
        from app.core.drivers.pipx import PipxManager
        return await PipxManager().search_packages(query)
