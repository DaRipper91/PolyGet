"""Package manager driver for the AUR, through an AUR helper (paru or yay)."""

import re
import shutil
from typing import Any
from urllib.parse import quote
from app.core.manager import DriverError, PackageManager, fetch_json, register_manager, run_capture

_HELPERS = ("paru", "yay")
# The AUR's own package-name rule; anything else can't be an AUR package.
_AUR_NAME_RE = re.compile(r"^[a-z0-9@._+-]+$")
_AUR = "https://aur.archlinux.org"


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
    asks_for_password = True  # the helper runs sudo itself
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

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return [_helper(), "-Rs", "--noconfirm"] + packages

    async def preview_remove(self, packages: list[str]) -> list[str]:
        # Installed AUR packages are ordinary pacman packages, so pacman resolves the removal.
        from app.core.drivers.pacman import PacmanManager
        return await PacmanManager().preview_remove(packages)

    async def get_build_script(self, package: str) -> tuple[str, str]:
        # AUR packages are built from user-submitted PKGBUILDs, which run arbitrary shell as you,
        # and the install command passes --noconfirm, so this is the only chance to read one.
        if not _AUR_NAME_RE.match(package):
            raise DriverError(f"'{package}' is not a valid AUR package name")
        # The PKGBUILD lives under the package *base*, which differs from the name for split packages.
        info = await fetch_json(f"{_AUR}/rpc/v5/info?arg[]={quote(package)}", label=f"{self.name} package lookup")
        results = info.get("results") if isinstance(info, dict) else None
        if not results:
            raise DriverError(f"'{package}' was not found in the AUR")
        base = results[0].get("PackageBase") or package
        url = f"{_AUR}/cgit/aur.git/plain/PKGBUILD?h={quote(base)}"
        script = await run_capture(
            ["curl", "-fsS", "--max-time", "15", url], label=f"{self.name} PKGBUILD fetch", timeout=20.0
        )
        return url, script

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # `-Ssa` restricts the search to the AUR (the Pacman driver already covers the repos).
        # Exit 1 means "no matches".
        out = await run_capture(
            [_helper(), "-Ssa", query], label=f"{self.name} search", timeout=20.0, ok_codes=(0, 1)
        )
        lines = out.splitlines()
        results = []
        # Two lines per result: "aur/name version (+votes popularity)" then an indented description.
        # Use len(lines) - (len(lines) % 2) so a trailing odd line (which can't form a pair)
        # is ignored rather than silently dropped via len(lines) - 1.
        for i in range(0, len(lines) - (len(lines) % 2), 2):
            header = lines[i].split()
            if len(header) >= 2:
                name = header[0].split("/", 1)[-1]
                results.append({
                    "name": name, "id": name,
                    "description": lines[i + 1].strip(), "version": header[1],
                })
        return results
