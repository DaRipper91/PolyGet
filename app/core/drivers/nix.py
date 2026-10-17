"""Package manager driver for Nix (the user profile, via the flakes-era `nix profile` CLI)."""

import json
import re
import shutil
from typing import Any
from app.core.manager import DriverError, PackageManager, register_manager, run_capture

_NIX = ["nix", "--extra-experimental-features", "nix-command flakes"]
_STORE_VERSION_RE = re.compile(r"-(\d[\w.+\-]*)$")


def _store_version(store_path: str) -> str:
    """Pull the version out of a store path like /nix/store/<hash>-ripgrep-14.1.0."""
    return (m.group(1) if (m := _STORE_VERSION_RE.search(store_path.rsplit("/", 1)[-1])) else "")


@register_manager
class NixManager(PackageManager):
    """Package manager driver for Nix profiles.

    Nix has no cheap "what is outdated" query, so update checks are unsupported rather than
    guessed; `profile upgrade` still works when asked for explicitly.
    """

    name: str = "Nix"
    category: str = "Universal"

    def is_available(self) -> bool:
        return shutil.which("nix") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        out = await run_capture(
            _NIX + ["profile", "list", "--json"], label=f"{self.name} installed-package query", timeout=30.0
        )
        try:
            data = json.loads(out)
        except ValueError as e:
            raise DriverError(f"{self.name} installed-package query failed: output was not valid JSON") from e
        elements = data.get("elements", {})
        if isinstance(elements, list):  # Nix < 2.20 numbered its profile entries
            elements = {str(i): e for i, e in enumerate(elements)}
        versions = {}
        for key, element in elements.items():
            paths = element.get("storePaths") or ([element["storePath"]] if element.get("storePath") else [])
            name = key if not key.isdigit() else (paths[0].rsplit("/", 1)[-1].split("-", 1)[-1] if paths else key)
            versions[name] = _store_version(paths[0]) if paths else ""
        return versions

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Nix has no cheap outdated-package query")

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return _NIX + ["profile", "upgrade"] + (packages if packages else ["--all"])

    def get_install_command(self, package: str) -> list[str]:
        return _NIX + ["profile", "install", package if "#" in package else f"nixpkgs#{package}"]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # The first search evaluates nixpkgs, which is slow; later ones hit Nix's eval cache.
        out = await run_capture(
            _NIX + ["search", "nixpkgs", query, "--json"], label=f"{self.name} search", timeout=180.0
        )
        try:
            data = json.loads(out)
        except ValueError as e:
            raise DriverError(f"{self.name} search failed: output was not valid JSON") from e
        results = []
        for attr, info in data.items():
            # Keys look like "legacyPackages.x86_64-linux.ripgrep".
            short = attr.split(".", 2)[-1]
            results.append({
                "name": info.get("pname", short), "id": f"nixpkgs#{short}",
                "description": info.get("description", "") or "", "version": info.get("version", "") or "",
            })
        return results
