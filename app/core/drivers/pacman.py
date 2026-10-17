"""Package manager driver for Pacman (Arch Linux and derivatives like CachyOS)."""

import asyncio
import re
import shutil
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, register_manager

_BREAKS = re.compile(r"breaks dependency '[^']*' required by (\S+)")


async def pacman_remove_preview(package: str, label: str = "Pacman") -> dict[str, list[str]]:
    """Dry-run `pacman -Rs` (--print needs no root). Exit 1 with "breaks dependency ...
    required by X" means pacman would refuse the removal because X still needs it."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pacman", "-Rsp", "--print-format", "%n", package,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except Exception as e:
        raise DriverError(f"{label} removal preview failed: {describe_error(e)}") from e
    if proc.returncode == 0:
        names = [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        return {"remove": names or [package], "blocked_by": []}
    blockers = sorted(set(_BREAKS.findall(stderr.decode(errors="ignore"))))
    if blockers:
        return {"remove": [package], "blocked_by": blockers}
    detail = stderr.decode(errors="ignore").strip().splitlines()
    raise DriverError(f"{label} removal preview failed: `pacman` exited with status "
                      f"{proc.returncode}{': ' + detail[-1] if detail else ''}")


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

    def get_remove_command(self, package: str) -> list[str]:
        # -s also drops dependencies nothing else needs; pacman refuses (rather than cascades)
        # when another installed package still needs the target.
        return ["pkexec", "pacman", "-Rs", "--noconfirm", package]

    async def preview_remove(self, package: str) -> dict[str, list[str]]:
        return await pacman_remove_preview(package, self.name)

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
