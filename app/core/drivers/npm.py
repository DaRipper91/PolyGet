import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class NpmManager(PackageManager):
    """Package manager driver for global NPM packages."""

    name: str = "NPM"
    category: str = "Language/Dev"

    def __init__(self) -> None:
        """Initialize the NPM package manager driver."""
        super().__init__()
        self._global_prefix: str | None = None

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
        # Fetch prefix first asynchronously
        try:
            prefix_proc = await asyncio.create_subprocess_exec(
                "npm", "config", "get", "prefix",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_prefix, _ = await asyncio.wait_for(prefix_proc.communicate(), timeout=5.0)
            if prefix_proc.returncode == 0 and stdout_prefix:
                self._global_prefix = stdout_prefix.decode(errors="ignore").strip()
        except Exception:
            try:
                prefix_proc.kill()
            except Exception:
                pass

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "outdated", "-g", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if not stdout:
                return []
            import json
            data = json.loads(stdout.decode(errors="ignore"))
        except Exception:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return []

        # `npm outdated -g --json` reports failures (registry errors, network
        # issues, etc.) as {"error": {...}} on stdout rather than a package
        # map. Left unchecked, that dict gets misread as a package literally
        # named "error" instead of surfacing the real failure.
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            message = err.get("summary") or err.get("detail") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"npm outdated failed: {message or 'unknown error'}")

        updates = []
        for name, info in data.items():
            updates.append({
                "name": name,
                "current": info.get("current", "Unknown"),
                "new": info.get("latest", "Latest")
            })
        return updates

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade global NPM packages.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        base_cmd = ["npm", "update", "-g"]
        if packages:
            base_cmd = base_cmd + packages

        import os

        prefix = self._global_prefix

        if not prefix:
            prefix = os.environ.get("NPM_CONFIG_PREFIX")

        if not prefix:
            # Fallback checks on standard locations if we can't find the prefix
            fallback_paths = ["/usr/lib/node_modules", "/usr/local/lib/node_modules", "/usr/local", "/usr"]
            for path in fallback_paths:
                if os.path.exists(path):
                    if not os.access(path, os.W_OK):
                        return ["sudo"] + base_cmd
                    else:
                        return base_cmd

        if prefix:
            if not os.access(prefix, os.W_OK):
                return ["sudo"] + base_cmd

        return base_cmd

    async def list_installed(self) -> list[str]:
        """List installed global NPM packages.

        Returns:
            list[str]: A list of installed package names.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "list", "-g", "--depth=0", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
            if not stdout:
                return []
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            dependencies = data.get("dependencies", {})
            return list(dependencies.keys())
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a global NPM package.

        Args:
            package (str): The package name to install.

        Returns:
            list[str]: The install command list.
        """
        return ["npm", "install", "-g", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search for NPM packages globally."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "search", "--json", query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if not stdout:
                return []
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            results = []
            if isinstance(data, list):
                for item in data[:20]:
                    results.append({
                        "name": item.get("name", ""),
                        "id": item.get("name", ""),
                        "description": item.get("description", ""),
                        "version": item.get("version", "")
                    })
            return results
        except Exception:
            return []
