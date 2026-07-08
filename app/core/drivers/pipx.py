import asyncio
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
            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    # Check if pip is available in its venv
                    import os
                    pipx_home = os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/share/pipx"))
                    pip_path = os.path.join(pipx_home, "venvs", name, "bin", "pip")
                    if os.path.exists(pip_path):
                        pip_proc = await asyncio.create_subprocess_exec(
                            pip_path, "list", "--outdated", "--json",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        pip_stdout, _ = await pip_proc.communicate()
                        if pip_stdout:
                            import json
                            pip_data = json.loads(pip_stdout.decode(errors="ignore"))
                            for item in pip_data:
                                if item.get("name") == name:
                                    updates.append({
                                        "name": name,
                                        "current": item.get("version", "Unknown"),
                                        "new": item.get("latest_version", "Latest")
                                    })
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
