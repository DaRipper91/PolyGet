"""Package manager driver for Elixir's Hex (globally installed Mix archives/escripts)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class HexManager(PackageManager):
    name: str = "Hex"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("mix") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "mix", "archive",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip().rstrip("*").strip()
                if line and line.endswith(".ez"):
                    installed.append(line.rsplit("-", 1)[0].replace(".ez", ""))
            return installed
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # Mix archives don't have a bulk "list what's outdated" command —
        # each would need an individual hex.pm version lookup. Left empty
        # rather than faking it; revisit if per-archive lookups prove cheap enough.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["mix", "archive.install", "hex"] + packages + ["--force"]
        return ["mix", "local.hex", "--force"]

    def get_install_command(self, package: str) -> list[str]:
        return ["mix", "archive.install", "hex", package, "--force"]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", f"https://hex.pm/api/packages?search={query}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": p.get("name", ""), "id": p.get("name", ""),
                     "description": (p.get("meta") or {}).get("description", ""),
                     "version": ((p.get("releases") or [{}])[0]).get("version", "")}
                    for p in data[:20]]
        except Exception:
            return []
