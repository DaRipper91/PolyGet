"""Package manager driver for Dart's pub (global-activated CLI packages)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class DartPubManager(PackageManager):
    name: str = "Dart Pub"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("dart") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "dart", "pub", "global", "list",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                if line.strip():
                    installed.append(line.split()[0])
            return installed
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # `dart pub global` has no built-in outdated-check across all globally
        # activated packages — only per-package via reactivation. Re-activating
        # every installed package just to detect drift is expensive and noisy,
        # so this intentionally returns [] rather than faking a check.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["dart", "pub", "global", "activate"] + packages
        return ["dart", "pub", "global", "activate"]  # no bulk-upgrade-all equivalent exists

    def get_install_command(self, package: str) -> list[str]:
        return ["dart", "pub", "global", "activate", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # pub.dev has a documented search API (unlike PyPI) — use it directly.
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", f"https://pub.dev/api/search?q={query}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": p.get("package", ""), "id": p.get("package", ""),
                     "description": "", "version": ""} for p in data.get("packages", [])[:20]]
        except Exception:
            return []
