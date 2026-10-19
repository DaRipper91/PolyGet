"""Package manager driver for Yarn (Node.js, global installs)."""

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, register_manager, run_capture


@register_manager
class YarnManager(PackageManager):
    name: str = "Yarn"
    category: str = "Language/Dev"
    changelog_url_template = "https://www.npmjs.com/package/{name}?activeTab=versions"

    def is_available(self) -> bool:
        return shutil.which("yarn") is not None

    async def _run(self, argv: list[str], timeout: float, cwd: Path | None = None):
        """Run argv capturing output, killing a hung child instead of hanging."""
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            raise
        return proc, stdout, stderr

    async def check_updates(self) -> list[dict[str, Any]]:
        # Yarn Classic has no `yarn global outdated` (it errors "Invalid subcommand"), so run
        # plain `yarn outdated` inside the global install directory that `yarn global dir` names.
        label = f"{self.name} update check"
        global_dir = Path((await run_capture(["yarn", "global", "dir"], label=label)).strip())
        if not (global_dir / "package.json").is_file():
            return []  # nothing has ever been installed globally
        try:
            proc, stdout, stderr = await self._run(["yarn", "outdated", "--json"], timeout=120.0, cwd=global_dir)
        except Exception as e:
            raise DriverError(f"{label} failed: {describe_error(e)}") from e
        updates = []
        errors = []
        for line in (stdout + b"\n" + stderr).decode(errors="ignore").splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("type") == "error":
                errors.append(str(obj.get("data", "")))
            elif obj.get("type") == "table":
                for row in obj.get("data", {}).get("body", []):
                    if len(row) >= 4:
                        updates.append({"name": row[0], "current": row[1], "new": row[3]})
        # `yarn outdated` exits 0 when everything is current and 1 when something is outdated;
        # an error line, any other status, or a 1 without a table means the scan itself broke.
        if errors or proc.returncode not in (0, 1) or (proc.returncode == 1 and not updates):
            detail = f": {errors[0]}" if errors else ""
            raise DriverError(f"{label} failed: yarn exited with status {proc.returncode}{detail}")
        return updates

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["yarn", "global", "add"] + packages
        return ["yarn", "global", "upgrade"]

    async def list_installed(self) -> list[str]:
        try:
            _, stdout, _ = await self._run(["yarn", "global", "list", "--depth=0"], timeout=10.0)
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("info") or "@" not in line:
                    continue
                # Format: '- packagename@version'
                name = line.lstrip("- ").rsplit("@", 1)[0]
                if name:
                    installed.append(name)
            return installed
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-package query failed: {describe_error(e)}"
            ) from e

    async def list_installed_versions(self) -> dict[str, str]:
        try:
            _, stdout, _ = await self._run(["yarn", "global", "list", "--depth=0"], timeout=10.0)
            versions = {}
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("info") or "@" not in line:
                    continue
                # Format: '- packagename@version'
                parts = line.lstrip("- ").rsplit("@", 1)
                if len(parts) == 2:
                    name, version = parts
                    if name:
                        versions[name] = version
            return versions
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-version query failed: {describe_error(e)}"
            ) from e

    def get_install_command(self, package: str) -> list[str]:
        return ["yarn", "global", "add", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["yarn", "global", "remove"] + packages

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Yarn Classic has no built-in search command; it shares npm's registry,
        # so delegate to the npm registry search API directly rather than
        # reinventing it — same registry, same package names.
        try:
            _, stdout, _ = await self._run(["npm", "search", "--json", query], timeout=15.0)
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": i.get("name", ""), "id": i.get("name", ""),
                     "description": i.get("description", ""), "version": i.get("version", "")}
                    for i in data[:20]] if isinstance(data, list) else []
        except Exception as e:
            raise DriverError(
                f"{self.name} search failed: {describe_error(e)}"
            ) from e
