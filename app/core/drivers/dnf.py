import asyncio
import shutil
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, register_manager, run_capture
from app.core.settings_store import get_settings

# Any dnf call may first refresh expired repo metadata, which routinely takes well over 15s.
DNF_TIMEOUT = 120.0


_ARCHES = {"x86_64", "aarch64", "noarch", "i686", "armv7hl", "ppc64le", "s390x"}


@register_manager
class DnfManager(PackageManager):
    """Package manager driver for DNF (Dandified YUM)."""

    name: str = "DNF"
    category: str = "System"
    changelog_url_template = "https://packages.fedoraproject.org/search?query={name}"

    def is_available(self) -> bool:
        """Check if dnf is installed and available in the system PATH.

        Returns:
            bool: True if dnf is available, False otherwise.
        """
        return shutil.which("dnf") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query DNF for outdated system packages that `dnf upgrade` will actually apply."""
        return await self._mark_vendor_blocked(await self._query_updates())

    async def _mark_vendor_blocked(self, updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flag upgrades that change vendor while dnf's allow_vendor_change is off.

        `dnf check-update` still lists those, but `dnf upgrade` skips them and exits 0, so they
        would sit in the list forever after every "successful" upgrade. Flagged entries get a
        `blocked` reason; packages on the user's dnf.allow_vendor_change list are left alone
        (get_upgrade_command passes --allow-vendor-change for them). Best-effort: if any query
        fails, the list is returned unflagged.
        """
        allowed = set(get_settings().get("dnf.allow_vendor_change", []))
        names = [u["name"] for u in updates if u["name"] not in allowed]
        if not names:
            return updates

        async def run(*args: str) -> str:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DNF_TIMEOUT)
            except Exception:
                proc.kill()
                await proc.wait()
                raise
            return stdout.decode(errors="ignore")

        def vendors(text: str) -> dict[str, str]:
            return dict(line.split(" ", 1) for line in text.splitlines() if " " in line)

        try:
            config = await run("dnf", "--dump-main-config")
            if "allow_vendor_change = 0" not in config:
                return updates
            new_vendor = vendors(await run(
                "dnf", "repoquery", "--upgrades", "--latest-limit=1",
                "--qf", "%{name} %{vendor}\n", *names
            ))
            old_vendor = vendors(await run("rpm", "-q", "--qf", "%{NAME} %{VENDOR}\n", *names))
        except Exception:
            return updates
        for u in updates:
            old, new = old_vendor.get(u["name"]), new_vendor.get(u["name"])
            if u["name"] in names and old and new and old != new:
                u["blocked"] = f"vendor change: {old} → {new}"
        return updates

    async def _query_updates(self) -> list[dict[str, Any]]:
        """Query DNF for outdated system packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        proc = None
        try:
            # First try using --json option (supported in DNF 5) without sudo
            proc = await asyncio.create_subprocess_exec(
                "dnf", "check-update", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DNF_TIMEOUT)
            if proc.returncode in (0, 100) and stdout:
                import json
                try:
                    data = json.loads(stdout.decode(errors="ignore"))
                    updates = []
                    upgrades = data.get("upgrades", [])
                    for item in upgrades:
                        pkg_name = item.get("name")
                        new_ver = item.get("evr")
                        if pkg_name and new_ver:
                            updates.append({
                                "name": pkg_name,
                                "current": "Installed",
                                "new": new_ver
                            })
                    return updates
                except json.JSONDecodeError:
                    pass
        except Exception:
            # A timed-out or otherwise-failed --json attempt must be killed here,
            # not just abandoned — otherwise it lingers in the background holding
            # DNF's system-repository lock, which blocks the fallback check right
            # below (and any later upgrade command) from ever acquiring it.
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass

        # Fallback to standard check-update parsing without sudo
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "check-update", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DNF_TIMEOUT)
            # DNF returns 100 when updates exist, 0 when none
            if proc.returncode not in (0, 100):
                raise RuntimeError("dnf update check failed")

            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and not parts[0].startswith("Last") and not parts[0].startswith("Upgrades") and not parts[0].startswith("Obsoleting"):
                    if "." in parts[0]:
                        pkg_name = parts[0].rsplit(".", 1)[0]
                        updates.append({"name": pkg_name, "current": "Installed", "new": parts[1]})
            return updates
        except Exception as e:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            raise RuntimeError(f"{self.name} update check failed: {describe_error(e)}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade system packages using DNF.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        if packages:
            # ponytail: the flag covers the whole transaction, so dependencies may switch vendor
            # too; split into two dnf runs if that ever matters.
            allowed = set(get_settings().get("dnf.allow_vendor_change", []))
            flag = ["--allow-vendor-change"] if allowed.intersection(packages) else []
            return ["pkexec", "dnf", "upgrade", "-y"] + flag + packages
        return ["pkexec", "dnf", "upgrade", "-y"]

    def get_sync_command(self) -> list[str] | None:
        """Get the command to sync repository metadata for DNF.

        Returns:
            list[str]: The sync command list.
        """
        return ["pkexec", "dnf", "makecache"]

    async def list_installed(self) -> list[str]:
        """List installed packages using DNF.

        Returns:
            list[str]: A list of installed package names.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "list", "--installed", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DNF_TIMEOUT)
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} installed-package query failed: "
                    f"`dnf list --installed` exited with status {proc.returncode}"
                )

            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and not parts[0].startswith("Installed") and not parts[0].startswith("Last"):
                    pkg_name = parts[0]
                    if "." in pkg_name:
                        pkg_name = pkg_name.rsplit(".", 1)[0]
                    installed.append(pkg_name)
            return installed
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-package query failed: {describe_error(e)}"
            ) from e

    async def list_installed_versions(self) -> dict[str, str]:
        """List installed DNF packages with versions.

        Returns:
            dict[str, str]: Mapping of package name -> version string (EVR format).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "list", "--installed", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DNF_TIMEOUT)
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} installed-version query failed: "
                    f"`dnf list --installed` exited with status {proc.returncode}"
                )

            versions = {}
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and not parts[0].startswith("Installed") and not parts[0].startswith("Last"):
                    pkg_name = parts[0]
                    if "." in pkg_name:
                        pkg_name = pkg_name.rsplit(".", 1)[0]
                    # parts[1] is the version (EVR: epoch:version-release)
                    versions[pkg_name] = parts[1]
            return versions
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} installed-version query failed: {describe_error(e)}"
            ) from e

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a package using DNF.

        Args:
            package (str): The name of the package to install.

        Returns:
            list[str]: The command list to install the package.
        """
        return ["pkexec", "dnf", "install", "-y", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["pkexec", "dnf", "remove", "-y"] + packages

    @staticmethod
    def _parse_removal_transaction(output: str) -> list[str]:
        """Package names from the "Removing:" sections of a dnf (4 or 5) transaction table."""
        names, in_section = [], False
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Transaction Summary"):
                break
            if stripped.endswith(":") and not line.startswith(" "):
                # Section headers: "Removing:", "Removing unused dependencies:", "Removing dependent packages:".
                in_section = stripped.startswith("Removing")
            elif in_section and line.startswith(" ") and stripped:
                first = stripped.split()[0]
                # dnf4 wraps a long name onto its own line; the continuation starts with the arch.
                if first not in _ARCHES:
                    names.append(first)
        return names

    async def preview_remove(self, packages: list[str]) -> list[str]:
        # --assumeno resolves the transaction and then declines it, exiting 1 by design.
        out = await run_capture(
            ["dnf", "remove", "--assumeno"] + packages,
            label=f"{self.name} removal preview", timeout=60.0, ok_codes=(0, 1),
        )
        names = self._parse_removal_transaction(out)
        if not names:
            raise DriverError(f"{self.name} removal preview found nothing to remove — are these packages installed?")
        return names

    supports_repos: bool = True

    async def list_repos(self) -> list[dict[str, Any]]:
        """List configured repositories/remotes for DNF.

        Returns:
            list[dict[str, Any]]: The configured repos. An empty list means the
                query ran and found none — never that the query failed.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "repolist", "--all", "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DNF_TIMEOUT)
            # A failed repolist would otherwise render as "no repositories configured",
            # which is a false claim about the system's state.
            if proc.returncode != 0:
                raise DriverError(
                    f"{self.name} repository query failed: "
                    f"`dnf repolist --all` exited with status {proc.returncode}"
                )
            repos = []
            lines = stdout.decode(errors="ignore").splitlines()
            if not lines:
                return []
            
            # Skip header line if present
            start_idx = 1 if "repo id" in lines[0].lower() else 0
            for line in lines[start_idx:]:
                import re
                parts = re.split(r'\s{2,}', line.strip())
                if len(parts) >= 2:
                    # Check status column (parts[2]) or prefix
                    enabled = True
                    if len(parts) >= 3:
                        status_str = parts[2].lower()
                        if status_str == "disabled":
                            enabled = False
                    elif parts[0].startswith("!"):
                        enabled = False
                    
                    repo_id = parts[0].lstrip("!*")
                    repo_name = parts[1]
                    repos.append({
                        "id": repo_id,
                        "name": repo_name,
                        "url": "",
                        "enabled": enabled
                    })
            return repos
        except DriverError:
            raise
        except Exception as e:
            raise DriverError(
                f"{self.name} repository query failed: {describe_error(e)}"
            ) from e

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        """Get the command to add a DNF repository or enable a COPR repo."""
        if repo_url_or_id.count("/") == 1 and not repo_url_or_id.startswith("http"):
            # COPR shorthand (e.g. "copr.fedorainfracloud.org/group_asahi/kernel" -> "group_asahi/kernel")
            return ["pkexec", "dnf", "copr", "enable", "-y", repo_url_or_id]
        return ["pkexec", "dnf", "config-manager", "--add-repo", repo_url_or_id]

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        """Get the command to disable a DNF repository."""
        return ["pkexec", "dnf", "config-manager", "--set-disabled", repo_id]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search for DNF system packages."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "dnf", "search", query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DNF_TIMEOUT)
            import re
            pattern = re.compile(r'^\s*([a-zA-Z0-9\-_+.]+)\.([a-zA-Z0-9_]+)\s+(.+)$')
            results = []
            for line in stdout.decode(errors="ignore").splitlines():
                match = pattern.match(line)
                if match:
                    pkg_name = match.group(1)
                    if any(x in pkg_name for x in ("-debuginfo", "-debugsource", ".src")):
                        continue
                    results.append({
                        "name": pkg_name,
                        "id": pkg_name,
                        "description": match.group(3),
                        "version": ""
                    })
            return results
        except Exception as e:
            raise DriverError(
                f"{self.name} search failed: {describe_error(e)}"
            ) from e
