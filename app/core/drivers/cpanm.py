"""Package manager driver for Perl's cpanminus (globally installed CPAN modules)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class CpanmManager(PackageManager):
    name: str = "cpanm"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("cpanm") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "perl", "-MExtUtils::Installed", "-e",
                "print join(qq(\\n), ExtUtils::Installed->new->modules)",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # No built-in bulk outdated-check without the separate `cpan-outdated`
        # tool, which isn't a safe assumption to have installed — return []
        # rather than silently depending on an optional third tool.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["cpanm"] + packages
        return ["cpanm", "--self-upgrade"]

    def get_install_command(self, package: str) -> list[str]:
        return ["cpanm", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # MetaCPAN has a real, documented public search API — use it directly.
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", f"https://fastapi.metacpan.org/v1/module/_search?q={query}&size=20",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            hits = data.get("hits", {}).get("hits", [])
            return [{"name": h["_source"].get("name", ""), "id": h["_source"].get("name", ""),
                     "description": "", "version": h["_source"].get("version", "")} for h in hits]
        except Exception:
            return []
