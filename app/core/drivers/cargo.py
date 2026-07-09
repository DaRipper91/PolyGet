import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class CargoManager(PackageManager):
    """Package manager driver for globally installed Rust binaries via Cargo."""

    name: str = "Cargo"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        """Check if cargo is installed and available in the system PATH.

        Returns:
            bool: True if cargo is available, False otherwise.
        """
        return shutil.which("cargo") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query Cargo-installed binaries for updates.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        try:
            if shutil.which("cargo-install-update") is None:
                return []
            proc = await asyncio.create_subprocess_exec(
                "cargo", "install-update", "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
            updates = []
            # Parse output: lines look like "pkg_name  current_version  latest_version  needs_update"
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and not parts[0].startswith("Package") and not parts[0].startswith("---"):
                    if parts[3].lower() == "yes":
                        updates.append({
                            "name": parts[0],
                            "current": parts[1],
                            "new": parts[2]
                        })
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade cargo binaries.

        Uses cargo-install-update if available, otherwise falls back to
        installing the cargo-update tool.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        if shutil.which("cargo-install-update") is not None:
            if packages:
                return ["cargo", "install-update"] + packages
            return ["cargo", "install-update", "-a"]
        return ["cargo", "install", "cargo-update"]

    async def list_installed(self) -> list[str]:
        """List installed packages via Cargo.

        Returns:
            list[str]: A list of installed package names.
        """
        try:
            if shutil.which("cargo-install-update") is None:
                return []
            proc = await asyncio.create_subprocess_exec(
                "cargo", "install-update", "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode != 0:
                return []

            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and not parts[0].startswith("Package") and not parts[0].startswith("---"):
                    installed.append(parts[0])
            return installed
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a cargo package.

        Args:
            package (str): The package name to install.

        Returns:
            list[str]: The install command list.
        """
        return ["cargo", "install", package]
