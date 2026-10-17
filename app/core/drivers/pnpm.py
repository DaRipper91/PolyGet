"""Package manager driver for pnpm (Node.js, global installs)."""

import asyncio
import shutil
import subprocess
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, register_manager


@register_manager
class PnpmManager(PackageManager):
    name: str = "pnpm"
    category: str = "Language/Dev"
    changelog_url_template = "https://www.npmjs.com/package/{name}?activeTab=versions"

    def __init__(self) -> None:
        super().__init__()
        self._pnpm_path: str | None = None
        self._shell_fallback: bool | None = None

    def is_available(self) -> bool:
        return shutil.which("pnpm") is not None

    def _resolve(self) -> str:
        if self._pnpm_path is None:
            self._pnpm_path = shutil.which("pnpm") or "pnpm"
        return self._pnpm_path

    def _needs_shell_fallback(self) -> bool:
        """Detect whether pnpm's binary needs an explicit `sh` hop.

        pnpm 11+ can ship its `pnpm` bin entry as a placeholder shim that a
        direct `execve` (what asyncio and Qt use) rejects with
        `[Errno 8] Exec format error`, even though an interactive shell retries
        it under `sh`. Detect this by actually running `pnpm --version`
        directly: if it fails with Exec format error or another OS error,
        route through `sh` explicitly via an argv list (never a shell string).

        Result is cached per instance so the probe runs at most once.
        """
        if self._shell_fallback is None:
            path = shutil.which("pnpm")
            needs = False
            if path:
                try:
                    subprocess.run(
                        [path, "--version"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5.0,
                    )
                    needs = False
                except (FileNotFoundError, OSError, subprocess.SubprocessError):
                    needs = True
            self._shell_fallback = needs
        return self._shell_fallback

    def _pnpm_argv(self, *args: str) -> list[str]:
        if self._needs_shell_fallback():
            return ["sh", self._resolve(), *args]
        return ["pnpm", *args]

    async def _run(self, argv: list[str], timeout: float):
        """Run argv capturing output, killing a hung child instead of hanging."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            raise
        return proc, stdout

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            _, stdout = await self._run(
                self._pnpm_argv("outdated", "--global", "--format", "json"), timeout=120.0
            )
            import json
            data = json.loads(stdout.decode(errors="ignore") or "{}")
            return [{"name": name, "current": info.get("current", ""), "new": info.get("latest", "")}
                    for name, info in data.items()]
        except Exception as e:
            raise RuntimeError(f"{self.name} update check failed: {describe_error(e)}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return self._pnpm_argv("add", "--global", *packages)
        return self._pnpm_argv("update", "--global")

    async def list_installed(self) -> list[str]:
        try:
            _, stdout = await self._run(
                self._pnpm_argv("list", "--global", "--depth=0", "--json"), timeout=10.0
            )
            import json
            data = json.loads(stdout.decode(errors="ignore") or "[]")
            deps = data[0].get("dependencies", {}) if data else {}
            return list(deps.keys())
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-package query failed: {describe_error(e)}"
            ) from e

    async def list_installed_versions(self) -> dict[str, str]:
        try:
            _, stdout = await self._run(
                self._pnpm_argv("list", "--global", "--depth=0", "--json"), timeout=10.0
            )
            import json
            data = json.loads(stdout.decode(errors="ignore") or "[]")
            deps = data[0].get("dependencies", {}) if data else {}
            return {name: info.get("version", "unknown") for name, info in deps.items()}
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-version query failed: {describe_error(e)}"
            ) from e

    def get_install_command(self, package: str) -> list[str]:
        return self._pnpm_argv("add", "--global", package)

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Same reasoning as Yarn — pnpm has no native search, shares npm's registry.
        try:
            _, stdout = await self._run(["npm", "search", "--json", query], timeout=15.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": i.get("name", ""), "id": i.get("name", ""),
                     "description": i.get("description", ""), "version": i.get("version", "")}
                    for i in data[:20]] if isinstance(data, list) else []
        except Exception as e:
            raise DriverError(
                f"{self.name} search failed: {describe_error(e)}"
            ) from e
