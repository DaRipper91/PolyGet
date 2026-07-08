import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class NpmManager(PackageManager):
    """Package manager driver for global NPM packages."""

    name: str = "NPM"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        """Check if npm is installed and available in the system PATH.

        Returns:
            bool: True if npm is available, False otherwise.
        """
        return shutil.which("npm") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query NPM for outdated global packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "outdated", "-g", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if not stdout:
                return []
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            updates = []
            for name, info in data.items():
                updates.append({
                    "name": name,
                    "current": info.get("current", "Unknown"),
                    "new": info.get("latest", "Latest")
                })
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade global NPM packages.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        base_cmd = ["npm", "update", "-g"]
        if packages:
            base_cmd = base_cmd + packages

        try:
            import subprocess
            import os
            res = subprocess.run(
                ["npm", "config", "get", "prefix"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if res.returncode == 0:
                prefix = res.stdout.strip()
                if not os.access(prefix, os.W_OK):
                    return ["sudo"] + base_cmd
        except Exception:
            pass
        return base_cmd
