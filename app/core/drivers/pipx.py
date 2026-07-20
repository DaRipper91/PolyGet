import asyncio
import json
import os
import shutil
import tempfile
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
        pipx_home = os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/share/pipx"))
        pip_path = os.path.join(pipx_home, "venvs", name, "bin", "pip")
        if not os.path.exists(pip_path):
            # No venv/pip for this package — nothing checkable, not a failure.
            return []

        try:
            pip_proc = await asyncio.create_subprocess_exec(
                pip_path, "list", "--outdated", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            pip_stdout, _ = await asyncio.wait_for(pip_proc.communicate(), timeout=12.0)
        except Exception as e:
            raise RuntimeError(f"Pipx per-package update check failed for '{name}': {e}") from e

        if not pip_stdout:
            return []

        try:
            pip_data = json.loads(pip_stdout.decode(errors="ignore"))
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Pipx per-package update check failed for '{name}': malformed pip output: {e}"
            ) from e

        results = []
        for item in pip_data:
            if item.get("name") == name:
                results.append({
                    "name": name,
                    "current": item.get("version", "Unknown"),
                    "new": item.get("latest_version", "Latest")
                })
        return results

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
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)

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
        except Exception as e:
            raise RuntimeError(f"{self.name} update check failed: {e}") from e

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
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
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

    from pathlib import Path
    _INDEX_CACHE_PATH = Path.home() / ".cache" / "polyget" / "pypi_simple_index.json"
    _INDEX_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 1 week
    _index_lock = asyncio.Lock()

    async def _ensure_index_cached(self) -> list[str]:
        """Download and cache the full list of PyPI package names, refreshing weekly.

        Writes are done via a temp file + atomic rename in the same directory, and a
        shared lock prevents two concurrent callers from both downloading and racing
        to write the cache file (which could otherwise interleave into corrupt JSON).
        """
        import json
        import time

        def _read_cache_if_fresh() -> list[str] | None:
            if not self._INDEX_CACHE_PATH.exists():
                return None
            age = time.time() - self._INDEX_CACHE_PATH.stat().st_mtime
            if age >= self._INDEX_MAX_AGE_SECONDS:
                return None
            try:
                return json.loads(self._INDEX_CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                return None

        cached = _read_cache_if_fresh()
        if cached is not None:
            return cached

        async with self._index_lock:
            # Re-check after acquiring the lock: another concurrent caller may have
            # already refreshed the cache while this one was waiting.
            cached = _read_cache_if_fresh()
            if cached is not None:
                return cached

            self._INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Fetch simple HTML or JSON from PyPI. PyPI simple API supports JSON simple v1 index!
                proc = await asyncio.create_subprocess_exec(
                    "curl", "-s", "-H", "Accept: application/vnd.pypi.simple.v1+json",
                    "https://pypi.org/simple/",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
                if stdout:
                    data = json.loads(stdout.decode(errors="ignore"))
                    names = [p["name"] for p in data.get("projects", [])]

                    fd, tmp_path = tempfile.mkstemp(
                        dir=self._INDEX_CACHE_PATH.parent,
                        prefix=".pypi_simple_index_",
                        suffix=".tmp",
                    )
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as f:
                            f.write(json.dumps(names))
                        os.replace(tmp_path, self._INDEX_CACHE_PATH)
                    except BaseException:
                        os.unlink(tmp_path)
                        raise
                    return names
            except Exception:
                pass
            return []

    async def _fetch_package_detail(self, name: str) -> dict[str, Any] | None:
        """Fetch a single package's description/version from PyPI's JSON API."""
        import json
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "-H", "User-Agent: PolyGet/1.0",
                f"https://pypi.org/pypi/{name}/json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if stdout:
                data = json.loads(stdout.decode(errors="ignore"))
                info = data.get("info", {})
                if info:
                    return {
                        "name": info.get("name", name),
                        "id": info.get("name", name),
                        "description": info.get("summary", ""),
                        "version": info.get("version", "")
                    }
        except Exception:
            pass
        return None

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search for Python packages on PyPI using local simple index cache substring matches."""
        try:
            names = await self._ensure_index_cached()
            if not names:
                return []

            query_lower = query.lower()
            matches = [n for n in names if query_lower in n.lower()][:20]

            details = await asyncio.gather(*(self._fetch_package_detail(name) for name in matches))
            return [detail for detail in details if detail is not None]
        except Exception:
            return []
