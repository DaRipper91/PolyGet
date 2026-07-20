"""Package manager driver for APT (Debian/Ubuntu)."""

import asyncio
import glob
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class AptManager(PackageManager):
    """Package manager driver for APT."""

    name: str = "APT"
    category: str = "System"

    def is_available(self) -> bool:
        """Check if apt-get is installed and available in the system PATH.

        Returns:
            bool: True if apt-get is available, False otherwise.
        """
        return shutil.which("apt-get") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Query APT for outdated packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt", "list", "--upgradable",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode != 0:
                raise RuntimeError("apt update check failed")

            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                # Format: "pkgname/suite,other-suite newversion arch [upgradable from: oldversion]"
                if "/" not in line or "upgradable from" not in line:
                    continue
                name = line.split("/", 1)[0].strip()
                # Strip the multiarch qualifier (e.g. "libc6:amd64" -> "libc6") so
                # names agree with list_installed()'s bare `apt-mark showmanual` output.
                name = name.split(":", 1)[0]
                parts = line.split()
                new_ver = parts[1] if len(parts) > 1 else "Unknown"
                current = line.split("upgradable from:", 1)[-1].strip().rstrip("]")
                updates.append({"name": name, "current": current or "Installed", "new": new_ver})
            return updates
        except Exception as e:
            raise RuntimeError(f"{self.name} update check failed: {e}") from e

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to upgrade APT-managed packages.

        Returns:
            list[str]: The upgrade command and its arguments.
        """
        if packages:
            return ["pkexec", "apt-get", "install", "--only-upgrade", "-y"] + packages
        return ["pkexec", "apt-get", "upgrade", "-y"]

    def get_sync_command(self) -> list[str] | None:
        """Get the command to sync/refresh APT repository metadata.

        Returns:
            list[str]: The sync command list.
        """
        return ["pkexec", "apt-get", "update"]

    async def list_installed(self) -> list[str]:
        """List manually installed APT packages.

        Returns:
            list[str]: A list of installed package names.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt-mark", "showmanual",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode != 0:
                return []
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install an APT package.

        Args:
            package (str): The name of the package to install.

        Returns:
            list[str]: The install command list.
        """
        return ["pkexec", "apt-get", "install", "-y", package]

    supports_repos: bool = True

    @staticmethod
    def _parse_legacy_sources(content: str) -> list[dict[str, Any]]:
        """Parse a one-line-per-entry sources.list-style file.

        Recognizes both `# deb ...` and `#deb ...` (no space) as disabled entries —
        both are syntactically valid in a sources.list.
        """
        repos = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            is_comment = line.startswith("#")
            body = line[1:].strip() if is_comment else line
            if not (body.startswith("deb ") or body.startswith("deb-src ")):
                continue
            repos.append({"id": body, "name": body, "url": body, "enabled": not is_comment})
        return repos

    @staticmethod
    def _parse_deb822_sources(content: str) -> list[dict[str, Any]]:
        """Parse a deb822-format `.sources` file (the Ubuntu 24.04+/Debian 12+ default).

        Stanzas are blank-line-delimited `Key: Value` blocks with `Types`, `URIs`,
        `Suites`, `Components`, and optionally `Enabled`. Continuation lines (indented)
        are folded into the preceding key's value.
        """
        repos: list[dict[str, Any]] = []

        def flush(lines: list[str]) -> None:
            fields: dict[str, str] = {}
            current_key: str | None = None
            for raw_line in lines:
                if raw_line.startswith(("#", ";")):
                    continue
                if raw_line[:1] in (" ", "\t") and current_key:
                    fields[current_key] += " " + raw_line.strip()
                    continue
                if ":" not in raw_line:
                    continue
                key, _, value = raw_line.partition(":")
                current_key = key.strip()
                fields[current_key] = value.strip()

            uris = fields.get("URIs", "").split()
            if not uris:
                return
            suites = fields.get("Suites", "").split()
            types_ = fields.get("Types", "deb")
            enabled = fields.get("Enabled", "yes").strip().lower() not in ("no", "false", "0")
            summary = " ".join(part for part in (types_, " ".join(uris), " ".join(suites)) if part)
            repos.append({"id": summary, "name": summary, "url": uris[0], "enabled": enabled})

        stanza: list[str] = []
        for raw_line in content.splitlines():
            if raw_line.strip() == "":
                if stanza:
                    flush(stanza)
                    stanza = []
                continue
            stanza.append(raw_line)
        if stanza:
            flush(stanza)
        return repos

    async def list_repos(self) -> list[dict[str, Any]]:
        """List configured APT repositories from sources.list and sources.list.d.

        Covers both the legacy one-line-per-entry format (`.list` files) and the
        deb822 stanza format (`.sources` files) that Ubuntu 24.04+/Debian 12+ ship
        as the default.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing active repos.
        """
        # apt has no `repolist`-equivalent CLI command the way dnf does, so
        # the sources files are parsed directly.
        repos = []
        legacy_sources = ["/etc/apt/sources.list"] + glob.glob("/etc/apt/sources.list.d/*.list")
        for path in legacy_sources:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            repos.extend(self._parse_legacy_sources(content))

        for path in glob.glob("/etc/apt/sources.list.d/*.sources"):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            repos.extend(self._parse_deb822_sources(content))

        return repos

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        """Get the command to add an APT repository."""
        return ["pkexec", "add-apt-repository", "-y", repo_url_or_id]

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        """Get the command to remove an APT repository."""
        return ["pkexec", "add-apt-repository", "--remove", "-y", repo_id]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search for APT packages."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt-cache", "search", query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            results = []
            for line in stdout.decode(errors="ignore").splitlines():
                if " - " not in line:
                    continue
                name, desc = line.split(" - ", 1)
                results.append({"name": name.strip(), "id": name.strip(), "description": desc.strip(), "version": ""})
            return results
        except Exception:
            return []
