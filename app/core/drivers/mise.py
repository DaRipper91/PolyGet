"""Package manager driver for mise (polyglot runtime/tool version manager, the asdf successor)."""

import json
import shutil
from typing import Any
from app.core.manager import DriverError, PackageManager, register_manager, run_capture


def _load(out: str, label: str) -> dict:
    try:
        data = json.loads(out or "{}")
    except ValueError as e:
        raise DriverError(f"{label} failed: output was not valid JSON") from e
    if not isinstance(data, dict):
        raise DriverError(f"{label} failed: unexpected JSON shape")
    return data


@register_manager
class MiseManager(PackageManager):
    """Runtimes and tools installed through mise (node, python, go, terraform, ...).

    Package names are mise tool names. `mise upgrade` stays inside the version each config file
    requests (e.g. `node@20` gets 20.x), which is why "new" can be lower than the absolute latest.
    """

    name: str = "Mise"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("mise") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        label = f"{self.name} update check"
        data = _load(await run_capture(["mise", "outdated", "--json"], label=label, timeout=60.0), label)
        updates = []
        for tool, info in data.items():
            if isinstance(info, dict) and info.get("current") and info.get("latest"):
                updates.append({"name": tool, "current": str(info["current"]), "new": str(info["latest"])})
        return updates

    async def list_installed_versions(self) -> dict[str, str]:
        label = f"{self.name} installed-tool query"
        data = _load(await run_capture(["mise", "ls", "--installed", "--json"], label=label, timeout=30.0), label)
        versions = {}
        for tool, entries in data.items():
            if isinstance(entries, list) and entries:
                # Prefer the version active in the current config; otherwise the newest listed.
                active = [e for e in entries if isinstance(e, dict) and e.get("active")]
                pick = (active or entries)[-1]
                versions[tool] = str(pick.get("version", "")) if isinstance(pick, dict) else ""
        return versions

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return ["mise", "upgrade", "--yes"] + (packages or [])

    def get_install_command(self, package: str) -> list[str]:
        # `use --global` installs it and records it in the global config, so it is on PATH everywhere.
        return ["mise", "use", "--global", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["mise", "uninstall", "--all"] + packages
