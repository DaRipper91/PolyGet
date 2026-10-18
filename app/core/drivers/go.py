"""Package manager driver for Go (binaries installed with `go install`)."""

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from app.core.janitor import dir_size, target
from app.core.manager import DriverError, PackageManager, describe_error, register_manager, run_capture

# `go version -m` prints build info as tab-separated lines: "\tpath\t<pkg>" and "\tmod\t<module>\t<version>\t<sum>".
_PATH_RE = re.compile(r"^\s+path\s+(\S+)", re.MULTILINE)
_MOD_RE = re.compile(r"^\s+mod\s+(\S+)\s+(\S+)", re.MULTILINE)


def _go_bin_dir() -> Path:
    """Resolve where `go install` puts binaries: GOBIN, else the first GOPATH entry's bin/."""
    try:
        out = subprocess.run(
            ["go", "env", "GOBIN", "GOPATH"], capture_output=True, text=True, timeout=10, check=True
        ).stdout.split("\n")
    except (OSError, subprocess.SubprocessError) as e:
        raise DriverError(f"Go failed to locate its bin directory: {describe_error(e)}") from e
    gobin, gopath = out[0].strip(), (out[1].strip() if len(out) > 1 else "")
    if gobin:
        return Path(gobin)
    return Path(gopath.split(os.pathsep)[0]) / "bin" if gopath else Path.home() / "go" / "bin"


def _scan_binaries() -> dict[str, tuple[str, str]]:
    """Map each installed Go binary's package path to (module path, version).

    Local-only (reads embedded build info, no network), so it is cheap enough to call from
    the synchronous command builders too.
    """
    bin_dir = _go_bin_dir()
    if not bin_dir.is_dir():
        return {}
    found: dict[str, tuple[str, str]] = {}
    for exe in sorted(p for p in bin_dir.iterdir() if p.is_file() and os.access(p, os.X_OK)):
        proc = subprocess.run(["go", "version", "-m", str(exe)], capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            continue  # not a Go executable
        pkg, mod = _PATH_RE.search(proc.stdout), _MOD_RE.search(proc.stdout)
        # Binaries built with `go build -o` report "command-line-arguments" and cannot be updated.
        if pkg and mod and pkg.group(1) != "command-line-arguments":
            found[pkg.group(1)] = (mod.group(1), mod.group(2))
    return found


@register_manager
class GoManager(PackageManager):
    """Package manager driver for Go-installed binaries.

    Packages are identified by their import path (e.g. golang.org/x/tools/gopls) because
    that, not the binary name, is what `go install <path>@latest` needs. Go has no registry
    search API, so search is unsupported.
    """

    name: str = "Go"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("go") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        try:
            return {pkg: ver for pkg, (_, ver) in (await asyncio.to_thread(_scan_binaries)).items()}
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(f"{self.name} installed-package query failed: {describe_error(e)}") from e

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            binaries = await asyncio.to_thread(_scan_binaries)
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(f"{self.name} update check failed: {describe_error(e)}") from e

        async def latest(module: str) -> str:
            out = await run_capture(
                ["go", "list", "-m", "-f", "{{.Version}}", f"{module}@latest"],
                label=f"{self.name} {module} lookup", timeout=30.0,
            )
            return out.strip()

        items = list(binaries.items())
        results = await asyncio.gather(*(latest(mod) for _, (mod, _) in items), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures and len(failures) == len(results):
            raise DriverError(f"{self.name} update check failed: {failures[0]}")
        return [
            {"name": pkg, "current": cur, "new": new}
            for (pkg, (_, cur)), new in zip(items, results)
            if not isinstance(new, Exception) and new and new != cur
        ]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        targets = packages or list(_scan_binaries())
        if not targets:
            raise DriverError(f"{self.name} has no installed binaries to upgrade")
        return ["go", "install"] + [f"{pkg}@latest" for pkg in targets]

    async def get_cleanup_targets(self) -> list[dict[str, Any]]:
        modcache = (await run_capture(["go", "env", "GOMODCACHE"], label=f"{self.name} cache query")).strip()
        size = await dir_size(Path(modcache)) if modcache else 0
        if not size:
            return []
        return [target(self.name, "cache", "Module cache", ["go", "clean", "-modcache"], size,
                       detail="downloaded module sources; builds fetch them again")]

    def get_install_command(self, package: str) -> list[str]:
        return ["go", "install", package if "@" in package else f"{package}@latest"]
