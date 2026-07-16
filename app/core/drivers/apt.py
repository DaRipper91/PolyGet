"""Package manager driver for APT (Debian/Ubuntu)."""

import asyncio
import glob
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class AptManager(PackageManager):
    """Package manager driver for APT."""

    name: str = "APT"
    category: str = "System"

    def is_available(self) -> bool:
        """Check if apt-get is installed and available in the system PATH.

        Returns:
            bool: True if apt-get is available, False otherwise.
        """
        return shutil.which("apt-get") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query APT for outdated packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt", "list", "--upgradable",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode != 0:
                return []

            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                # Format: "pkgname/suite,other-suite newversion arch [upgradable from: oldversion]"
                if "/" not in line or "upgradable from" not in line:
                    continue
                name = line.split("/", 1)[0].strip()
                parts = line.split()
                new_ver = parts[1] if len(parts) > 1 else "Unknown"
                current = line.split("upgradable from:", 1)[-1].strip().rstrip("]")
                updates.append({"name": name, "current": current or "Installed", "new": new_ver})
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade APT-managed packages.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        if packages:
            return ["pkexec", "apt-get", "install", "--only-upgrade", "-y"] + packages
        return ["pkexec", "apt-get", "upgrade", "-y"]

    def get_sync_command(self) -> list[str] | None:
        """Get the command to sync/refresh APT repository metadata.

        Returns:
            list[str]: The sync command list.
        """
        return ["pkexec", "apt-get", "update"]

    async def list_installed(self) -> list[str]:
        """List manually installed APT packages.

        Returns:
            list[str]: A list of installed package names.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt-mark", "showmanual",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode != 0:
                return []
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install an APT package.

        Args:
            package (str): The name of the package to install.

        Returns:
            list[str]: The install command list.
        """
        return ["pkexec", "apt-get", "install", "-y", package]

    supports_repos: bool = True

    async def list_repos(self) -> list[dict[str, Any]]:
        """List configured APT repositories from sources.list and sources.list.d.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing active repos.
        """
        # apt has no `repolist`-equivalent CLI command the way dnf does, so
        # the sources files are parsed directly.
        repos = []
        sources = ["/etc/apt/sources.list"] + glob.glob("/etc/apt/sources.list.d/*.list")
        for path in sources:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        enabled = line.startswith("deb ") or line.startswith("deb-src ")
                        if not enabled and not line.startswith("# deb"):
                            continue
                        raw = line.lstrip("# ").strip()
                        repos.append({"id": raw, "name": raw, "url": raw, "enabled": enabled})
            except OSError:
                continue
        return repos

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        """Get the command to add an APT repository."""
        return ["pkexec", "add-apt-repository", "-y", repo_url_or_id]

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        """Get the command to remove an APT repository."""
        return ["pkexec", "add-apt-repository", "--remove", "-y", repo_id]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search for APT packages."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt-cache", "search", query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            results = []
            for line in stdout.decode(errors="ignore").splitlines():
                if " - " not in line:
                    continue
                name, desc = line.split(" - ", 1)
                results.append({"name": name.strip(), "id": name.strip(), "description": desc.strip(), "version": ""})
            return results
        except Exception:
            return []
