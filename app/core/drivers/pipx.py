import asyncio
import json
import os
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class PipxManager(PackageManager):
    """Package manager driver for Pipx-installed Python applications."""

    name: str = "Pipx"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        """Check if pipx is installed and available in the system PATH.

        Returns:
            bool: True if pipx is available, False otherwise.
        """
        return shutil.which("pipx") is not None

    async def _check_package(self, name: str) -> list[dict[str, Any]]:
        """Check a single package for updates using its venv pip.

        Args:
            name (str): The name of the pipx package.

        Returns:
            list[dict[str, Any]]: A list containing update details if found, or empty list.
        """
        try:
            pipx_home = os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/share/pipx"))
            pip_path = os.path.join(pipx_home, "venvs", name, "bin", "pip")
            if not os.path.exists(pip_path):
                return []

            pip_proc = await asyncio.create_subprocess_exec(
                pip_path, "list", "--outdated", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            pip_stdout, _ = await pip_proc.communicate()
            if pip_stdout:
                pip_data = json.loads(pip_stdout.decode(errors="ignore"))
                results = []
                for item in pip_data:
                    if item.get("name") == name:
                        results.append({
                            "name": name,
                            "current": item.get("version", "Unknown"),
                            "new": item.get("latest_version", "Latest")
                        })
                return results
        except Exception:
            pass
        return []

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query Pipx for outdated packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        try:
            # We can run a fast list check
            proc = await asyncio.create_subprocess_exec(
                "pipx", "list", "--short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()

            packages = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    packages.append(parts[0])

            if not packages:
                return []

            # Gather all package check tasks concurrently
            tasks = [self._check_package(pkg) for pkg in packages]
            results = await asyncio.gather(*tasks)

            # Flatten results list
            updates = []
            for result in results:
                updates.extend(result)
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade all Pipx-managed applications.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        if packages:
            return ["pipx", "upgrade"] + packages
        return ["pipx", "upgrade-all"]

    async def list_installed(self) -> list[str]:
        """List installed pipx packages.

        Returns:
            list[str]: A list of installed package names.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "pipx", "list", "--short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return []

            packages = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    packages.append(parts[0])
            return packages
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a pipx package.

        Args:
            package (str): The package to install.

        Returns:
            list[str]: The install command list.
        """
        return ["pipx", "install", package]

