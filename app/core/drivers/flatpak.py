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
                    "flatpak", "list", "--columns=application,version,branch,active", "--json",
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
                            version = pkg.get("version") or pkg.get("branch") or "Installed"
                            commit = pkg.get("active_commit") or ""
                            installed_map[app_id] = {
                                "version": version,
                                "commit": commit
                            }
            except Exception:
                pass

            # 2. Query Flatpak for updates
            proc = await asyncio.create_subprocess_exec(
                "flatpak", "remote-ls", "--updates", "--columns=application,version,branch,commit", "--json",
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
                    new_ver = item.get("version") or item.get("branch") or "Update"
                    remote_commit = item.get("commit") or ""
                    
                    inst_info = installed_map.get(app_id, {"version": "Installed", "commit": ""})
                    current_ver = inst_info["version"]
                    local_commit = inst_info["commit"]

                    # If version strings are the same, append commit info to make the drift distinct
                    if current_ver == new_ver and local_commit and remote_commit:
                        # Truncate hashes for display cleaniness (e.g. first 8 characters)
                        current_ver = f"{current_ver} ({local_commit[:8]})"
                        new_ver = f"{new_ver} ({remote_commit[:8]})"
                    elif current_ver == new_ver and remote_commit:
                        new_ver = f"{new_ver} (Rebuild: {remote_commit[:8]})"

                    updates.append({
                        "name": app_id,
                        "current": current_ver,
                        "new": new_ver
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

    async def list_installed(self) -> list[str]:
        """List installed Flatpak packages.

        Returns:
            list[str]: A list of installed package application IDs.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "flatpak", "list", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                return []
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            installed = []
            for pkg in data:
                app_id = pkg.get("application_id")
                if app_id:
                    installed.append(app_id)
            return installed
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a Flatpak package.

        Args:
            package (str): The package ID to install.

        Returns:
            list[str]: The install command list.
        """
        return ["flatpak", "install", "-y", package]
