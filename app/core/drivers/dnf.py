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
            # First try using --json option (supported in DNF 5) with sudo -S
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-S", "dnf", "check-update", "--json",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            proc.stdin.write(b"0\n")
            await proc.stdin.drain()
            proc.stdin.close()
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

        # Fallback to standard check-update parsing with sudo -S
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-S", "dnf", "check-update", "--quiet",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            proc.stdin.write(b"0\n")
            await proc.stdin.drain()
            proc.stdin.close()
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
            return ["sudo", "dnf", "upgrade", "-y"] + packages
        return ["sudo", "dnf", "upgrade", "-y"]

    def get_sync_command(self) -> list[str] | None:
        """Get the command to sync repository metadata for DNF.

        Returns:
            list[str]: The sync command list.
        """
        return ["sudo", "dnf", "makecache"]
