"""Package manager driver for Pacman (Arch Linux and derivatives like CachyOS)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class PacmanManager(PackageManager):
    """Package manager driver for Pacman."""

    name: str = "Pacman"
    category: str = "System"

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
            raise RuntimeError(f"{self.name} update check failed: {e}") from e

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
                return []
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["pkexec", "pacman", "-S", "--noconfirm", package]

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
        except Exception:
            return []
