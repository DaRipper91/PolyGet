"""Package manager driver for Homebrew (macOS Homebrew and Linuxbrew share one CLI)."""

import json
import shutil
import sys
from pathlib import Path
from typing import Any
from app.core.manager import DriverError, PackageManager, register_manager, run_capture

# Brew is rarely on PATH for GUI launches, so probe its standard install prefixes too.
_PREFIX_CANDIDATES = (
    "/opt/homebrew/bin/brew",                  # macOS, Apple Silicon
    "/usr/local/bin/brew",                     # macOS, Intel
    "/home/linuxbrew/.linuxbrew/bin/brew",     # Linuxbrew, system-wide
    str(Path.home() / ".linuxbrew" / "bin" / "brew"),  # Linuxbrew, per-user
)


def _brew() -> str | None:
    found = shutil.which("brew")
    if found:
        return found
    return next((c for c in _PREFIX_CANDIDATES if Path(c).is_file()), None)


def _as_list(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else ([str(value)] if value else [])


@register_manager
class HomebrewManager(PackageManager):
    """Package manager driver for Homebrew on macOS and Linux.

    Casks exist only on macOS, so cask queries are skipped on Linux.
    """

    name: str = "Homebrew"
    category: str = "Universal"
    supports_repos: bool = True

    def is_available(self) -> bool:
        return _brew() is not None

    @staticmethod
    def _kinds() -> tuple[str, ...]:
        return ("--formula", "--cask") if sys.platform == "darwin" else ("--formula",)

    async def check_updates(self) -> list[dict[str, Any]]:
        out = await run_capture([_brew(), "outdated", "--json=v2"], label=f"{self.name} update check", timeout=60.0)
        try:
            data = json.loads(out)
        except ValueError as e:
            raise DriverError(f"{self.name} update check failed: output was not valid JSON") from e
        updates = []
        for entry in data.get("formulae", []) + data.get("casks", []):
            installed = _as_list(entry.get("installed_versions"))
            updates.append({
                "name": entry["name"],
                "current": installed[-1] if installed else "?",
                "new": str(entry.get("current_version", "?")),
            })
        return updates

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return [_brew(), "upgrade"] + (packages or [])

    def get_sync_command(self) -> list[str] | None:
        return [_brew(), "update"]

    async def list_installed_versions(self) -> dict[str, str]:
        versions = {}
        for kind in self._kinds():
            out = await run_capture(
                [_brew(), "list", kind, "--versions"], label=f"{self.name} installed-package query", timeout=30.0
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:  # "name v1 v2": the last listed version is the newest
                    versions[parts[0]] = parts[-1]
        return versions

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    def get_install_command(self, package: str) -> list[str]:
        return [_brew(), "install", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return [_brew(), "uninstall"] + packages

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Exit 1 means "no matches". Off a TTY brew prints one name per line under "==> Formulae"
        # / "==> Casks" headings. `--desc` is avoided: it matches descriptions only, not names.
        out = await run_capture(
            [_brew(), "search", query], label=f"{self.name} search", timeout=30.0, ok_codes=(0, 1)
        )
        results = []
        for line in out.splitlines():
            name = line.strip()
            if name and not name.startswith("==>"):
                results.append({"name": name, "id": name, "description": "", "version": ""})
        return results

    async def list_repos(self) -> list[dict[str, Any]]:
        out = await run_capture([_brew(), "tap"], label=f"{self.name} tap query")
        repos = []
        for tap in (line.strip() for line in out.splitlines()):
            if "/" in tap:
                user, repo = tap.split("/", 1)
                repos.append({"id": tap, "name": tap, "url": f"https://github.com/{user}/homebrew-{repo}", "enabled": True})
        return repos

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        return [_brew(), "tap", repo_url_or_id]

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        return [_brew(), "untap", repo_id]
