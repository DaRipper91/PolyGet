import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class FlatpakManager(PackageManager):
    """Package manager driver for Flatpak universal packages."""

    name: str = "Flatpak"
    category: str = "Universal"

    def is_available(self) -> bool:
        """Check if flatpak is installed and available in the system PATH.

        Returns:
            bool: True if flatpak is available, False otherwise.
        """
        return shutil.which("flatpak") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query Flatpak for outdated universal packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        try:
            # 1. Fetch currently installed flatpaks to map application_id -> installed version
            installed_map = {}
            try:
                list_proc = await asyncio.create_subprocess_exec(
                    "flatpak", "list", "--json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                list_stdout, _ = await list_proc.communicate()
                if list_stdout:
                    import json
                    installed_data = json.loads(list_stdout.decode(errors="ignore"))
                    for pkg in installed_data:
                        app_id = pkg.get("application_id")
                        if app_id:
                            # Use version, fallback to branch, then default to "Installed"
                            installed_map[app_id] = pkg.get("version") or pkg.get("branch") or "Installed"
            except Exception:
                pass

            # 2. Query Flatpak for updates
            proc = await asyncio.create_subprocess_exec(
                "flatpak", "remote-ls", "--updates", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if not stdout:
                return []
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            updates = []
            for item in data:
                app_id = item.get("application_id")
                if app_id:
                    new_version = item.get("version") or item.get("branch") or "Update"
                    current_version = installed_map.get(app_id, "Installed")
                    updates.append({
                        "name": app_id,
                        "current": current_version,
                        "new": new_version
                    })
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade packages using Flatpak.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        if packages:
            return ["flatpak", "update", "-y"] + packages
        return ["flatpak", "update", "-y"]

    def get_sync_command(self) -> list[str] | None:
        """Get the command to sync repository metadata for Flatpak.

        Returns:
            list[str]: The sync command list.
        """
        return ["flatpak", "update", "--appstream"]
