"""Package manager driver for the AUR, through an AUR helper (paru or yay)."""

import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager, run_capture

_HELPERS = ("paru", "yay")


def _helper() -> str | None:
    """Return the preferred AUR helper found on PATH (paru before yay)."""
    return next((h for h in _HELPERS if shutil.which(h)), None)


@register_manager
class AurManager(PackageManager):
    """Package manager driver for the Arch User Repository.

    Helpers refuse to run as root (makepkg forbids it) and escalate with sudo themselves,
    so unlike the Pacman driver no command here is wrapped in pkexec.
    """

    name: str = "AUR"
    category: str = "System"

    def is_available(self) -> bool:
        return _helper() is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        # `-Qua` exits 1 when there is nothing to update, like `pacman -Qu`.
        out = await run_capture(
            [_helper(), "-Qua"], label=f"{self.name} update check", timeout=60.0, ok_codes=(0, 1)
        )
        updates = []
        for line in out.splitlines():
            parts = line.split()
            # Format: "pkgname old_version -> new_version"
            if len(parts) >= 4 and parts[2] == "->":
                updates.append({"name": parts[0], "current": parts[1], "new": parts[3]})
        return updates

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return [_helper(), "-S", "--noconfirm"] + packages
        return [_helper(), "-Sua", "--noconfirm"]

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def list_installed_versions(self) -> dict[str, str]:
        # `-Qm` lists foreign packages: everything installed that no sync repo provides.
        out = await run_capture(["pacman", "-Qm"], label=f"{self.name} installed-package query")
        versions = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                versions[parts[0]] = parts[1]
        return versions

    def get_install_command(self, package: str) -> list[str]:
        return [_helper(), "-S", "--noconfirm", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # `-Ssa` restricts the search to the AUR (the Pacman driver already covers the repos).
        # Exit 1 means "no matches".
        out = await run_capture(
            [_helper(), "-Ssa", query], label=f"{self.name} search", timeout=20.0, ok_codes=(0, 1)
        )
        lines = out.splitlines()
        results = []
        # Two lines per result: "aur/name version (+votes popularity)" then an indented description.
        for i in range(0, len(lines) - 1, 2):
            header = lines[i].split()
            if len(header) >= 2:
                name = header[0].split("/", 1)[-1]
                results.append({
                    "name": name, "id": name,
                    "description": lines[i + 1].strip(), "version": header[1],
                })
        return results
