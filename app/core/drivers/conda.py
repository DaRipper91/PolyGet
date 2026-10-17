"""Package manager driver for Conda (packages in the base or active environment)."""

import json
import shutil
from typing import Any
from app.core.manager import DriverError, PackageManager, register_manager, run_capture

_BINARIES = ("conda", "mamba")


def _conda() -> str | None:
    return next((b for b in _BINARIES if shutil.which(b)), None)


def _parse(out: str, label: str) -> Any:
    try:
        return json.loads(out)
    except ValueError as e:
        raise DriverError(f"{label} failed: output was not valid JSON") from e


@register_manager
class CondaManager(PackageManager):
    """Package manager driver for Conda (or Mamba, which shares its CLI).

    Operates on whichever environment is active, which is `base` for a GUI launch.
    """

    name: str = "Conda"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return _conda() is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        label = f"{self.name} update check"
        out = await run_capture(
            [_conda(), "update", "--all", "--dry-run", "--json"], label=label, timeout=180.0
        )
        actions = _parse(out, label).get("actions") or {}
        # An upgrade shows up as an UNLINK of the old version plus a LINK of the new one.
        old = {p["name"]: p["version"] for p in actions.get("UNLINK", [])}
        return [
            {"name": p["name"], "current": old[p["name"]], "new": p["version"]}
            for p in actions.get("LINK", [])
            if p["name"] in old and old[p["name"]] != p["version"]
        ]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return [_conda(), "update", "-y"] + (packages if packages else ["--all"])

    async def list_installed_versions(self) -> dict[str, str]:
        label = f"{self.name} installed-package query"
        out = await run_capture([_conda(), "list", "--json"], label=label, timeout=60.0)
        return {p["name"]: p["version"] for p in _parse(out, label)}

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    def get_install_command(self, package: str) -> list[str]:
        return [_conda(), "install", "-y", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        label = f"{self.name} search"
        # Exit 1 with a JSON error body means "no matches" (PackagesNotFoundError).
        out = await run_capture(
            [_conda(), "search", f"*{query}*", "--json"], label=label, timeout=120.0, ok_codes=(0, 1)
        )
        data = _parse(out, label)
        if "error" in data and "PackagesNotFoundError" not in str(data.get("exception_name", "")):
            raise DriverError(f"{label} failed: {data['error']}")
        results = []
        for name, builds in data.items():
            if isinstance(builds, list) and builds:
                results.append({"name": name, "id": name, "description": "", "version": str(builds[-1].get("version", ""))})
        return results
