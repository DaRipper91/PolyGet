"""Package manager driver for Pacman (Arch Linux and derivatives like CachyOS)."""

import asyncio
import re
import shutil
from typing import Any
from app.core.janitor import target
from app.core.manager import DriverError, PackageManager, describe_error, register_manager, run_capture

_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4}
_SIZE_RE = re.compile(r"([\d.]+)\s*(B|KiB|MiB|GiB|TiB)")


def _to_bytes(text: str) -> int | None:
    m = _SIZE_RE.search(text)
    return int(float(m.group(1)) * _UNITS[m.group(2)]) if m else None

# pacman's "removing X breaks dependency 'X' required by Y" — Y blocks the removal.
_BREAKS = re.compile(r"breaks dependency '[^']*' required by (\S+)")


@register_manager
class PacmanManager(PackageManager):
    """Package manager driver for Pacman."""

    name: str = "Pacman"
    category: str = "System"
    changelog_url_template = "https://archlinux.org/packages/?q={name}"

    def is_available(self) -> bool:
        return shutil.which("pacman") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Qu",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            # pacman -Qu returns 1 when there are no updates, not just when there's an error —
            # only treat it as a real failure if stdout is also empty.
            if proc.returncode not in (0, 1):
                raise RuntimeError("pacman update check failed")
            if not stdout:
                return []

            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                # Format: "pkgname old_version -> new_version" (optionally with "[ignored]" suffix)
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "->":
                    updates.append({"name": parts[0], "current": parts[1], "new": parts[3]})
            return updates
        except Exception as e:
            raise RuntimeError(f"{self.name} update check failed: {describe_error(e)}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["pkexec", "pacman", "-S", "--noconfirm"] + packages
        return ["pkexec", "pacman", "-Syu", "--noconfirm"]

    def get_sync_command(self) -> list[str] | None:
        return ["pkexec", "pacman", "-Sy"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Qq",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} installed-package query failed: "
                    f"`pacman -Q` exited with status {proc.returncode}"
                )
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-package query failed: {describe_error(e)}"
            ) from e

    async def list_installed_versions(self) -> dict[str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Q",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} installed-version query failed: "
                    f"`pacman -Q` exited with status {proc.returncode}"
                )
            versions = {}
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    versions[parts[0]] = parts[1]
            return versions
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-version query failed: {describe_error(e)}"
            ) from e

    def get_install_command(self, package: str) -> list[str]:
        return ["pkexec", "pacman", "-S", "--noconfirm", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["pkexec", "pacman", "-Rs", "--noconfirm"] + packages

    async def preview_remove(self, packages: list[str]) -> list[str]:
        # `--print` resolves the transaction without root; a missing package or a broken
        # dependency exits non-zero. Read stderr directly (run_capture keeps only its first
        # line) so a blocked removal can name the packages that still need it.
        label = f"{self.name} removal preview"
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Rs", "--print", "--print-format", "%n", *packages,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20.0)
        except Exception as e:
            raise DriverError(f"{label} failed: {describe_error(e)}") from e
        if proc.returncode == 0:
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        err = stderr.decode(errors="ignore")
        needed_by = sorted(set(_BREAKS.findall(err)))
        if needed_by:
            raise DriverError(f"{self.name} won't remove {', '.join(packages)}: still needed by "
                              f"{', '.join(needed_by)}")
        detail = err.strip().splitlines()
        raise DriverError(f"{label} failed: `pacman` exited with status {proc.returncode}"
                          f"{': ' + detail[-1] if detail else ''}")

    async def get_cleanup_targets(self) -> list[dict[str, Any]]:
        targets = []
        # -Qdtq: installed as a dependency, required by nothing. Exits 1 when there are none.
        out = await run_capture(["pacman", "-Qdtq"], label=f"{self.name} orphan query", ok_codes=(0, 1))
        orphans = [line.strip() for line in out.splitlines() if line.strip()]
        if orphans:
            info = await run_capture(["pacman", "-Qi"] + orphans, label=f"{self.name} orphan size query")
            sizes = [_to_bytes(line) for line in info.splitlines() if line.startswith("Installed Size")]
            targets.append(target(
                self.name, "orphans", "Orphaned dependencies",
                ["pkexec", "pacman", "-Rns", "--noconfirm"] + orphans,
                sum(s for s in sizes if s) if sizes else None, orphans,
                "installed as dependencies, no longer required by anything",
            ))
        if shutil.which("paccache"):
            # Dry run: "==> finished dry run: 25 candidates (disk space saved: 456.78 MiB)".
            out = await run_capture(["paccache", "-dk2"], label=f"{self.name} cache query", timeout=60.0)
            saved = _to_bytes(out.split("disk space saved:", 1)[1]) if "disk space saved:" in out else None
            if saved:
                targets.append(target(
                    self.name, "cache", "Package cache", ["pkexec", "paccache", "-rk2"], saved,
                    detail="old package versions, keeping the 2 newest of each",
                ))
        else:
            targets.append(target(
                self.name, "cache", "Package cache", ["pkexec", "pacman", "-Sc", "--noconfirm"],
                detail="cached versions of packages no longer installed (install pacman-contrib for sizes)",
            ))
        return targets

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Ss", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            results = []
            lines = stdout.decode(errors="ignore").splitlines()
            # pacman -Ss prints two lines per result: "repo/name version" then an indented description
            for i in range(0, len(lines) - 1, 2):
                header = lines[i].split()
                if len(header) >= 2:
                    repo_name = header[0]
                    name = repo_name.split("/", 1)[-1]
                    version = header[1]
                    description = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    results.append({"name": name, "id": name, "description": description, "version": version})
            return results
        except Exception as e:
            raise DriverError(
                f"{self.name} search failed: {describe_error(e)}"
            ) from e
