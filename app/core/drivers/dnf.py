import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class DnfManager(PackageManager):
    """Package manager driver for DNF (Dandified YUM)."""

    name: str = "DNF"
    category: str = "System"

    def is_available(self) -> bool:
        """Check if dnf is installed and available in the system PATH.

        Returns:
            bool: True if dnf is available, False otherwise.
        """
        return shutil.which("dnf") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query DNF for outdated system packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        try:
            # First try using --json option (supported in DNF 5) without sudo
            proc = await asyncio.create_subprocess_exec(
                "dnf", "check-update", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode in (0, 100) and stdout:
                import json
                try:
                    data = json.loads(stdout.decode(errors="ignore"))
                    updates = []
                    upgrades = data.get("upgrades", [])
                    for item in upgrades:
                        pkg_name = item.get("name")
                        new_ver = item.get("evr")
                        if pkg_name and new_ver:
                            updates.append({
                                "name": pkg_name,
                                "current": "Installed",
                                "new": new_ver
                            })
                    return updates
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

        # Fallback to standard check-update parsing without sudo
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "check-update", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            # DNF returns 100 when updates exist, 0 when none
            if proc.returncode not in (0, 100):
                return []

            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and not parts[0].startswith("Last") and not parts[0].startswith("Upgrades") and not parts[0].startswith("Obsoleting"):
                    if "." in parts[0]:
                        pkg_name = parts[0].rsplit(".", 1)[0]
                        updates.append({"name": pkg_name, "current": "Installed", "new": parts[1]})
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade system packages using DNF.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        if packages:
            return ["pkexec", "dnf", "upgrade", "-y"] + packages
        return ["pkexec", "dnf", "upgrade", "-y"]

    def get_sync_command(self) -> list[str] | None:
        """Get the command to sync repository metadata for DNF.

        Returns:
            list[str]: The sync command list.
        """
        return ["pkexec", "dnf", "makecache"]

    async def list_installed(self) -> list[str]:
        """List installed packages using DNF.

        Returns:
            list[str]: A list of installed package names.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "list", "--installed", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return []

            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and not parts[0].startswith("Installed") and not parts[0].startswith("Last"):
                    pkg_name = parts[0]
                    if "." in pkg_name:
                        pkg_name = pkg_name.rsplit(".", 1)[0]
                    installed.append(pkg_name)
            return installed
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a package using DNF.

        Args:
            package (str): The name of the package to install.

        Returns:
            list[str]: The command list to install the package.
        """
        return ["pkexec", "dnf", "install", "-y", package]

    supports_repos: bool = True

    async def list_repos(self) -> list[dict[str, Any]]:
        """List configured repositories/remotes for DNF."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "repolist", "--all", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            repos = []
            lines = stdout.decode(errors="ignore").splitlines()
            if not lines:
                return []
            
            # Skip header line if present
            start_idx = 1 if "repo id" in lines[0].lower() else 0
            for line in lines[start_idx:]:
                import re
                parts = re.split(r'\s{2,}', line.strip())
                if len(parts) >= 2:
                    # Check status column (parts[2]) or prefix
                    enabled = True
                    if len(parts) >= 3:
                        status_str = parts[2].lower()
                        if "disabled" in status_str:
                            enabled = False
                    elif parts[0].startswith("!"):
                        enabled = False
                    
                    repo_id = parts[0].lstrip("!*")
                    repo_name = parts[1]
                    repos.append({
                        "id": repo_id,
                        "name": repo_name,
                        "url": "",
                        "enabled": enabled
                    })
            return repos
        except Exception:
            return []

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        """Get the command to add a DNF repository or enable a COPR repo."""
        if repo_url_or_id.count("/") == 1 and not repo_url_or_id.startswith("http"):
            # COPR shorthand (e.g. "copr.fedorainfracloud.org/group_asahi/kernel" -> "group_asahi/kernel")
            return ["pkexec", "dnf", "copr", "enable", "-y", repo_url_or_id]
        return ["pkexec", "dnf", "config-manager", "--add-repo", repo_url_or_id]

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        """Get the command to disable a DNF repository."""
        return ["pkexec", "dnf", "config-manager", "--set-disabled", repo_id]
