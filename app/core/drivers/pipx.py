import asyncio
import json
import os
import re
import shutil
import tempfile
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, register_manager, run_capture

# A pipx "package_or_url" that is just a project name or requirement ("ruff", "ruff==0.1", "pkg[extra]") is looked up on
# the index. Anything with a path separator, a URL, a VCS prefix, or an archive suffix names a source of its own.
_LOCAL_SOURCE_RE = re.compile(r"[/\\]|://|^git\+|^file:|\.(?:whl|tar\.gz|zip)$")


def _is_local_source(package_or_url: str) -> bool:
    """True if the app was installed from a path, URL or VCS checkout rather than from the package index."""
    return bool(_LOCAL_SOURCE_RE.search(package_or_url))


@register_manager
class PipxManager(PackageManager):
    """Package manager driver for Pipx-installed Python applications."""

    name: str = "Pipx"
    category: str = "Language/Dev"
    changelog_url_template = "https://pypi.org/project/{name}/#history"

    async def _local_source_apps(self) -> set[str]:
        """Apps installed from a local or VCS source, which an index lookup would wrongly compare with an
        unrelated same-named PyPI project (a local `six 0.0.1` would read as outdated against PyPI's `six`).

        If the metadata cannot be read, nothing is excluded: the index check is kept rather than hiding an app.
        """
        try:
            data = json.loads(await run_capture(["pipx", "list", "--json"], label=f"{self.name} source query", timeout=15.0))
            venvs = data.get("venvs")
        except (DriverError, ValueError, AttributeError):
            return set()
        if not isinstance(venvs, dict):
            return set()
        return {
            name for name, venv in venvs.items()
            if isinstance(venv, dict)
            and _is_local_source(str(venv.get("metadata", {}).get("main_package", {}).get("package_or_url", "")))
        }

    def is_available(self) -> bool:
        """Check if pipx is installed and available in the system PATH.

        Returns:
            bool: True if pipx is available, False otherwise.
        """
        return shutil.which("pipx") is not None

    async def _check_package(self, name: str) -> list[dict[str, Any]]:
        """Check a single package for updates by asking pipx to run pip inside its venv.

        `pipx runpip` is used instead of a venv's own `bin/pip` because current pipx builds venvs
        without one (it drives pip, or uv, from outside), so a path-based check found nothing
        checkable for every package and reported a clean system while apps were outdated.

        Args:
            name (str): The name of the pipx package.

        Returns:
            list[dict[str, Any]]: A list containing update details if found, or empty list.

        Raises:
            DriverError: The check itself failed (command error, non-zero exit, malformed output).
        """
        try:
            pip_proc = await asyncio.create_subprocess_exec(
                "pipx", "runpip", name, "list", "--outdated", "--format=json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            pip_stdout, pip_stderr = await asyncio.wait_for(pip_proc.communicate(), timeout=30.0)
        except Exception as e:
            raise DriverError(f"Pipx per-package update check failed for '{name}': {describe_error(e)}") from e

        if pip_proc.returncode not in (0, None):
            detail = pip_stderr.decode(errors="ignore").strip().splitlines()
            suffix = f": {detail[-1]}" if detail else ""
            raise DriverError(
                f"Pipx per-package update check failed for '{name}': "
                f"`pipx runpip` exited with status {pip_proc.returncode}{suffix}"
            )

        if not pip_stdout.strip():
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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)

            if proc.returncode != 0:
                detail = stderr.decode(errors="ignore").strip().splitlines()
                suffix = f": {detail[-1]}" if detail else ""
                raise DriverError(
                    f"{self.name} update check failed: "
                    f"`pipx list --short` exited with status {proc.returncode}{suffix}"
                )

            packages = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    packages.append(parts[0])

            if not packages:
                return []

            local = await self._local_source_apps()
            packages = [pkg for pkg in packages if pkg not in local]
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
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(f"{self.name} update check failed: {describe_error(e)}") from e

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
                raise DriverError(
                    f"{self.name} installed-package query failed: "
                    f"`pipx list --short` exited with status {proc.returncode}"
                )

            packages = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    packages.append(parts[0])
            return packages
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-package query failed: {describe_error(e)}"
            ) from e

    async def list_installed_versions(self) -> dict[str, str]:
        """List installed pipx packages with versions.

        Returns:
            dict[str, str]: Mapping of package name -> version string.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "pipx", "list", "--short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} installed-version query failed: "
                    f"`pipx list --short` exited with status {proc.returncode}"
                )

            versions = {}
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    # Extract version from the second part (e.g., "1.2.3" or "1.2.3*")
                    version = parts[1].rstrip("*")
                    versions[name] = version
            return versions
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-version query failed: {describe_error(e)}"
            ) from e

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a pipx package.

        Args:
            package (str): The package to install.

        Returns:
            list[str]: The install command list.
        """
        return ["pipx", "install", package]

    removes_one_at_a_time = True

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["pipx", "uninstall", packages[0]]

    from pathlib import Path
    _INDEX_CACHE_PATH = Path.home() / ".cache" / "polyget" / "pypi_simple_index.json"
    _INDEX_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 1 week
    # One lock per event loop: GUI workers each run their own loop, and before Python 3.12 a
    # Lock used in one loop raises in another. The atomic rename covers writers across loops.
    import weakref
    _index_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()

    async def _ensure_index_cached(self) -> list[str]:
        """Download and cache the full list of PyPI package names, refreshing weekly.

        Writes are done via a temp file + atomic rename in the same directory, and a
        shared lock prevents two concurrent callers from both downloading and racing
        to write the cache file (which could otherwise interleave into corrupt JSON).

        Raises:
            DriverError: The index could not be fetched, or the response was not a
                usable index. This used to return [], which `search_packages` then
                reported as "no packages matched" -- a dead PyPI index was
                indistinguishable from an honest empty result, and the DriverError
                wrapper around the caller could not catch it, because the failure was
                swallowed one level deeper.
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

        lock = self._index_locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())
        async with lock:
            # Re-check after acquiring the lock: another concurrent caller may have
            # already refreshed the cache while this one was waiting.
            cached = _read_cache_if_fresh()
            if cached is not None:
                return cached

            self._INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Fetch the PyPI simple index. The v1 JSON API returns {"projects": [...]}.
            try:
                proc = await asyncio.create_subprocess_exec(
                    "curl", "-s", "-H", "Accept: application/vnd.pypi.simple.v1+json",
                    "https://pypi.org/simple/",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except Exception as e:
                raise DriverError(
                    f"{self.name} could not fetch the PyPI package index: {describe_error(e)}"
                ) from e

            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} could not fetch the PyPI package index: "
                    f"`curl` exited with status {proc.returncode}"
                )
            if not stdout:
                raise DriverError(
                    f"{self.name} received an empty response from the PyPI package index"
                    + (f": {stderr.decode(errors='ignore').strip()[:120]}" if stderr else "")
                )

            try:
                data = json.loads(stdout.decode(errors="ignore"))
            except json.JSONDecodeError as e:
                # An HTML error page or a proxy interception, not an index.
                raise DriverError(
                    f"{self.name} got a malformed PyPI package index (not JSON): {e}"
                ) from e

            projects = data.get("projects") if isinstance(data, dict) else None
            if not isinstance(projects, list) or not projects:
                # pypi.org/simple/ is never legitimately empty, so this means the
                # response was not the index we asked for.
                raise DriverError(
                    f"{self.name} got an unusable PyPI package index "
                    "(no 'projects' list in the response)"
                )
            names = [p["name"] for p in projects if isinstance(p, dict) and "name" in p]

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

    async def _fetch_package_detail(self, name: str) -> dict[str, Any] | None:
        """Fetch a single package's description/version from PyPI's JSON API.

        Returns:
            dict | None: The package detail, or None if the package is listed in the
                index but carries no `info` block.

        Raises:
            DriverError: The fetch itself failed. Returning None here previously made
                a matched package vanish from the results with no indication, since the
                caller filtered None out and could not distinguish "no such package"
                from "PyPI was unreachable".
        """
        import json
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "-H", "User-Agent: PolyGet/1.0",
                f"https://pypi.org/pypi/{name}/json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except Exception as e:
            raise DriverError(
                f"{self.name} could not fetch details for '{name}': {describe_error(e)}"
            ) from e

        if proc.returncode != 0:
            raise DriverError(
                f"{self.name} could not fetch details for '{name}': "
                f"`curl` exited with status {proc.returncode}"
            )
        if not stdout:
            raise DriverError(f"{self.name} received an empty response for '{name}'")

        try:
            data = json.loads(stdout.decode(errors="ignore"))
        except json.JSONDecodeError as e:
            raise DriverError(
                f"{self.name} got a malformed response for '{name}' (not JSON): {e}"
            ) from e

        info = data.get("info", {}) if isinstance(data, dict) else {}
        if not info:
            return None  # listed in the index but carries no info block
        return {
            "name": info.get("name", name),
            "id": info.get("name", name),
            "description": info.get("summary", ""),
            "version": info.get("version", "")
        }

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search for Python packages on PyPI using local simple index cache substring matches."""
        try:
            names = await self._ensure_index_cached()
            query_lower = query.lower()
            matches = [n for n in names if query_lower in n.lower()][:20]
            if not matches:
                # A true empty: the index was read successfully and nothing matched.
                return []

            # Detail fetches are best-effort per package, so one unreachable package
            # must not discard the other 19 matches. If every one of them failed the
            # search produced nothing, and reporting "no results" would be a lie --
            # surface the failure instead.
            gathered = await asyncio.gather(
                *(self._fetch_package_detail(name) for name in matches),
                return_exceptions=True,
            )
            results = [
                d for d in gathered
                if not isinstance(d, BaseException) and d is not None
            ]
            failures = [d for d in gathered if isinstance(d, BaseException)]
            if failures and not results:
                raise failures[0]
            return results
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} search failed: {describe_error(e)}"
            ) from e
