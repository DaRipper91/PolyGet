"""Package manager driver for RubyGems (globally installed Ruby gems)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, register_manager


@register_manager
class GemManager(PackageManager):
    """Package manager driver for RubyGems."""

    name: str = "RubyGems"
    category: str = "Language/Dev"
    changelog_url_template = "https://rubygems.org/gems/{name}/versions"

    def is_available(self) -> bool:
        return shutil.which("gem") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        proc = None
        try:
            # `--bulk-threshold 10` forces RubyGems to pull compact bulk specification
            # indices rather than dispatching 100+ separate HTTP roundtrips for each
            # installed gem. On a system with 120 installed gems, this cuts scan time
            # by more than half (down from ~50-120s to ~20s) and avoids network stalls.
            cmd = ["gem", "outdated", "--bulk-threshold", "10"]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
            except asyncio.TimeoutError:
                if proc is not None:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                raise DriverError(f"{self.name} update check timed out after 180s")

            # Fallback to standard `gem outdated` if an older gem binary rejects --bulk-threshold
            if proc.returncode != 0 and b"bulk-threshold" in stderr:
                proc = await asyncio.create_subprocess_exec(
                    "gem", "outdated",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
                except asyncio.TimeoutError:
                    if proc is not None:
                        try:
                            proc.kill()
                            await proc.wait()
                        except Exception:
                            pass
                    raise DriverError(f"{self.name} update check timed out after 180s")

            if proc.returncode != 0:
                detail = stderr.decode(errors="ignore").strip().splitlines()
                suffix = f": {detail[-1]}" if detail else ""
                raise DriverError(
                    f"{self.name} update check failed: "
                    f"`gem outdated` exited with status {proc.returncode}{suffix}"
                )
            updates = []
            # Format: "gemname (current < available)"
            import re
            pattern = re.compile(r'^([a-zA-Z0-9_\-]+)\s+\(([^\s]+)\s*<\s*([^\s)]+)\)')
            for line in stdout.decode(errors="ignore").splitlines():
                match = pattern.match(line.strip())
                if match:
                    updates.append({"name": match.group(1), "current": match.group(2), "new": match.group(3)})
            return updates
        except DriverError:
            raise
        except Exception as e:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            raise DriverError(f"{self.name} update check failed: {describe_error(e)}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        # --no-document skips rdoc/ri generation (often duplicated across two
        # installed rdoc versions), which otherwise makes every gem's docs parse
        # and install multiple times and turns a 20-second update into a 110-second
        # one with native C extension builds still running.
        if packages:
            return ["gem", "update", "--no-document"] + packages
        return ["gem", "update", "--no-document"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "list", "--local",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} installed-package query failed: "
                    f"`gem list --local` exited with status {proc.returncode}"
                )
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                if line.strip() and "(" in line:
                    installed.append(line.split("(")[0].strip())
            return installed
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-package query failed: {describe_error(e)}"
            ) from e

    async def list_installed_versions(self) -> dict[str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "list", "--local",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} installed-version query failed: "
                    f"`gem list --local` exited with status {proc.returncode}"
                )
            versions = {}
            for line in stdout.decode(errors="ignore").splitlines():
                if line.strip() and "(" in line:
                    name = line.split("(")[0].strip()
                    # Extract version: "gemname (version1, version2, ...)"
                    ver_str = line.split("(")[1].rstrip(")").split(",")[0].strip()
                    versions[name] = ver_str
            return versions
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-version query failed: {describe_error(e)}"
            ) from e

    def get_install_command(self, package: str) -> list[str]:
        return ["gem", "install", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["gem", "uninstall", "--all", "--executables"] + packages

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "search", "--remote", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            results = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line and "(" in line and not line.startswith("*"):
                    name = line.split("(")[0].strip()
                    version = line.split("(")[1].rstrip(")").split(",")[0].strip()
                    results.append({"name": name, "id": name, "description": "", "version": version})
            return results
        except Exception as e:
            raise DriverError(
                f"{self.name} search failed: {describe_error(e)}"
            ) from e
