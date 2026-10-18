"""Base package manager interface and discovery utilities."""

import asyncio
import importlib
import json
import logging
from pathlib import Path
from typing import Type, Any

logger = logging.getLogger(__name__)


def describe_error(e: Exception) -> str:
    """Render an exception for display, falling back to its type name when str(e) is
    empty — notably a bare asyncio.TimeoutError, whose str() is always '', which would
    otherwise surface to the user as a blank, seemingly-nothing-happened error message.
    """
    return str(e) or type(e).__name__


class DriverError(RuntimeError):
    """A driver query failed for a reason the user should be told about.

    Distinguishes "this manager has nothing to report" from "this manager's query
    broke". Historically every driver ended these queries in `except Exception:
    return []`, which made a hung subprocess, a missing binary, and a genuinely empty
    result all look identical to callers — a scan could report a clean system while
    the driver was in fact dead.

    Drivers raise this instead of returning an empty collection when the query
    failed, and return the empty collection only when the query genuinely succeeded
    with nothing to report. Callers that need the distinction can use
    `NotImplementedError` (query not supported by this manager) as they already do.
    """


async def run_capture(
    argv: list[str],
    *,
    label: str,
    timeout: float = 15.0,
    ok_codes: tuple[int, ...] = (0,),
    cwd: str | Path | None = None,
) -> str:
    """Run a read-only query command and return its stdout, mapping every failure to DriverError.

    `ok_codes` lists exit statuses that still carry a valid answer (e.g. `pacman -Qu`
    exits 1 when nothing is outdated). Anything else, a hang, or a missing binary
    raises, so a dead query is never mistaken for an empty result.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except Exception as e:
        raise DriverError(f"{label} failed: {describe_error(e)}") from e
    if proc.returncode not in ok_codes:
        detail = stderr.decode(errors="ignore").strip().splitlines()
        suffix = f": {detail[0]}" if detail else ""
        raise DriverError(f"{label} failed: `{argv[0]}` exited with status {proc.returncode}{suffix}")
    return stdout.decode(errors="ignore")


async def fetch_json(url: str, *, label: str, timeout: float = 15.0) -> Any:
    """GET a JSON document via curl (the same transport the Pipx driver uses)."""
    out = await run_capture(
        ["curl", "-fsS", "--max-time", str(int(timeout)), "-H", "Accept: application/json", url],
        label=label, timeout=timeout + 5.0,
    )
    try:
        return json.loads(out)
    except ValueError as e:
        raise DriverError(f"{label} failed: response was not valid JSON") from e


class PackageManager:
    """Base class defining the interface for all package manager drivers."""

    name: str = "Base"
    category: str = "Base"
    # Where a human reads release notes for a package; "{name}" is replaced with the package
    # name. None means this manager has no per-package page worth linking to.
    changelog_url_template: str | None = None

    def changelog_url(self, package: str) -> str | None:
        from urllib.parse import quote
        if self.changelog_url_template is None:
            return None
        return self.changelog_url_template.format(name=quote(package, safe="@/"))

    async def still_outdated(self, packages: list[str]) -> list[str]:
        """Which of `packages` this manager still reports as outdated (raises DriverError if the
        check fails). Used after an upgrade, since several tools exit 0 having changed nothing."""
        wanted = set(packages)
        return sorted({u.get("name") for u in await self.check_updates()} & wanted)

    async def still_installed(self, packages: list[str]) -> list[str]:
        """Which of `packages` this manager still lists as installed (raises DriverError if the check
        fails). Used after a removal, for the same reason as `still_outdated`."""
        return sorted(set(packages) & set(await self.list_installed()))

    def is_available(self) -> bool:
        """Check if the package manager's binary is available in the system PATH.

        Returns:
            bool: True if available, False otherwise.
        """
        raise NotImplementedError("Subclasses must implement is_available()")

    async def get_self_version(self) -> str | None:
        """Return the package manager's own version string, or None if undetectable.

        The default implementation runs ``{binary} --version`` and returns the
        first line of output. Drivers override this when the binary name differs
        from the driver name or the version flag is non-standard.
        """
        import shutil
        binary = shutil.which(self.name.lower())
        if binary is None:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            line = stdout.decode(errors="ignore").strip().splitlines()
            return line[0].strip() if line else None
        except Exception:
            return None

    async def check_self_update(self) -> dict[str, str] | None:
        """Check whether the package manager itself has a newer version available.

        Returns:
            dict with 'current' and 'latest' keys, or None when the manager has
            no self-update mechanism or the check is unsupported.
        """
        return None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Asynchronously query the package manager for outdated packages.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing available updates,
                where each dict contains package details (e.g., name, current version,
                new version).
        """
        raise NotImplementedError("Subclasses must implement check_updates()")

    async def check_vulnerabilities(self) -> list[dict[str, Any]]:
        """Optionally query the package manager or audit tool for security advisories.

        Returns:
            list[dict[str, Any]]: List of dicts with 'name', 'severity', and 'advisory'.
                An empty list means the query ran and found nothing.

        Raises:
            NotImplementedError: This manager exposes no vulnerability data. Callers
                already treat this as "unsupported" rather than "failed".
            DriverError: A scanner was available but the query failed, OR no scanner
                is installed. Both matter: "no scanner" must not read as "no
                vulnerabilities", which is the failure this distinction exists to
                prevent.
        """
        raise NotImplementedError(f"{self.name} does not support vulnerability scanning")

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        """Get the command to perform the package upgrades.

        Args:
            packages (list[str]): Optional list of specific packages to upgrade.

        Returns:
            list[str]: The command and its arguments as a list of strings.
        """
        raise NotImplementedError("Subclasses must implement get_upgrade_command()")

    def get_sync_command(self) -> list[str] | None:
        """Get the command to sync/refresh repository metadata.

        Returns:
            list[str] | None: The sync command, or None if not supported/required.
        """
        return None

    async def list_installed(self) -> list[str]:
        """Get a list of installed package names.

        Returns:
            list[str]: A list of installed package names. An empty list means the
                query ran and found nothing installed.

        Raises:
            DriverError: The query failed. Drivers must not return an empty list on
                failure — that is indistinguishable from a clean system.
        """
        raise NotImplementedError("Subclasses must implement list_installed()")

    async def list_installed_versions(self) -> dict[str, str]:
        """Get a mapping of installed package names to their versions.

        Returns:
            dict[str, str]: A dict mapping package name -> version string. An empty
                dict means the query ran and found nothing.

        Raises:
            DriverError: The query failed.
        """
        return {}

    def get_install_command(self, package: str) -> list[str]:
        """Get the command list to install a package.

        Args:
            package (str): The name of the package to install.

        Returns:
            list[str]: The command list to install the package.
        """
        raise NotImplementedError("Subclasses must implement get_install_command()")

    # True for tools that prompt for the sudo password themselves even though their commands
    # don't start with pkexec/sudo (AUR helpers call sudo internally). The GUI counts these as
    # "needs your admin password" alongside pkexec-prefixed commands.
    asks_for_password: bool = False

    async def get_build_script(self, package: str) -> tuple[str, str]:
        """Return (source URL, text) of the script that installing `package` would execute.

        For managers that build from user-submitted recipes (the AUR's PKGBUILDs), so the user can
        read what will run before it runs. Most managers install prebuilt artifacts and leave this
        unimplemented.

        Raises:
            NotImplementedError: Packages from this manager don't come with a reviewable script.
            DriverError: The package doesn't exist or the script couldn't be fetched.
        """
        raise NotImplementedError(f"{self.name} packages have no build script to review")

    async def get_cleanup_targets(self) -> list[dict[str, Any]]:
        """Reclaimable space this manager can free: orphans, caches, leftover data.

        Returns:
            list[dict]: Targets built with `app.core.janitor.target()`, each carrying the command
                that cleans it and `bytes` (None when the size can't be known before running).
                Only targets with something to clean are returned.

        Raises:
            NotImplementedError: This manager has nothing PolyGet knows how to clean.
            DriverError: A query failed. Never guess: a target built from a failed query
                (e.g. "leftover data" when the installed list didn't load) could delete real data.
        """
        raise NotImplementedError(f"{self.name} has no cleanup targets")

    # True for tools whose remove command takes exactly one package (e.g. `pipx uninstall`);
    # callers then build one command per package instead of passing a list.
    removes_one_at_a_time: bool = False

    def get_remove_command(self, packages: list[str]) -> list[str]:
        """Get the command to uninstall packages.

        Args:
            packages (list[str]): Package names, as `list_installed()` reports them. A
                single-package tool (`removes_one_at_a_time`) only ever receives one.

        Returns:
            list[str]: The command and its arguments.

        Raises:
            NotImplementedError: This manager has no uninstall command.
        """
        raise NotImplementedError(f"{self.name} does not support removing packages")

    async def preview_remove(self, packages: list[str]) -> list[str]:
        """Return every package removing `packages` would take out, dependencies included.

        Only system managers resolve dependencies on removal, so only they override this.

        Raises:
            NotImplementedError: No dry-run is available; the remove command is the whole plan.
            DriverError: The dry-run failed — typically a package that isn't installed, or one
                that other installed packages still depend on.
        """
        raise NotImplementedError(f"{self.name} has no removal dry-run")

    def get_install_command_for(self, item: dict[str, Any]) -> list[str]:
        """Command to install a search/Store result (as returned by search_packages()).

        Drivers whose results carry more than the package id (Flatpak's remote) override this;
        everyone else installs by id.
        """
        return self.get_install_command(item["id"])

    def get_self_install_command(self) -> list[str] | None:
        """Get the command to install this manager itself on the current distro.

        Returns:
            list[str] | None: Command list, or None if unknown/unsupported.
        """
        return None

    supports_repos: bool = False

    async def list_repos(self) -> list[dict[str, Any]]:
        """List configured repositories/remotes for this manager.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing active repos,
                where each dict has at least 'id', 'name', 'url', 'enabled'. An empty
                list means the query ran and found no repos — never that it failed.

        Raises:
            NotImplementedError: This manager has no repository concept. Callers
                already treat this as "unsupported" rather than "failed".
            DriverError: The query failed. Without this, a broken `dnf repolist`
                renders as "no repositories configured" — a false claim about the
                system, on a page whose purpose is to show the system's real state.
        """
        raise NotImplementedError("This manager does not support repo listing")

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        """Get the command to add a repository/remote.

        Args:
            repo_url_or_id (str): The repository URL, path, or ID to add.

        Returns:
            list[str]: The command and its arguments.
        """
        raise NotImplementedError("This manager does not support adding repos")

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        """Get the command to remove a repository/remote.

        Args:
            repo_id (str): The repository identifier to remove.

        Returns:
            list[str]: The command and its arguments.
        """
        raise NotImplementedError("This manager does not support removing repos")

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search this manager's package source for a query string.

        Args:
            query (str): The search query.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing matching packages.
                Each dict must contain: 'name', 'id', 'description', 'version'.
                Callers will add the 'source' key themselves. An empty list means the
                search ran and found nothing — never that it failed.

        Raises:
            NotImplementedError: This manager has no programmatic search (e.g. Julia
                has no registry search API). Callers already report this as
                "unsupported" rather than a failed query.
            DriverError: The search failed — a dead subprocess, an unreachable
                registry, malformed output. Search is best-effort across many
                heterogeneous registries, so callers surface this per manager and
                keep the results from the managers that did answer; they must not
                treat it as a fatal error.
        """
        raise NotImplementedError(f"{self.name} does not support package search")


# Registry of all driver classes
_REGISTRY: list[Type[PackageManager]] = []


def register_manager(cls: Type[PackageManager]) -> Type[PackageManager]:
    """Decorator to register a package manager class."""
    _REGISTRY.append(cls)
    return cls


def discover_managers() -> list[PackageManager]:
    """Discover and return instances of all available package managers.

    Returns:
        list[PackageManager]: A list of available package manager driver instances.
    """
    # Import drivers to trigger their decorators
    try:
        importlib.import_module("app.core.drivers")
    except ImportError as e:
        logger.exception("Failed to import app.core.drivers — no managers will be discovered")
        raise

    active = []
    for cls in _REGISTRY:
        inst = cls()
        if inst.is_available():
            active.append(inst)
    return active


def get_all_managers() -> list[PackageManager]:
    """Return instances of all registered package manager drivers (regardless of availability).

    Returns:
        list[PackageManager]: A list of all registered package manager driver instances.
    """
    try:
        importlib.import_module("app.core.drivers")
    except ImportError as e:
        logger.exception("Failed to import app.core.drivers — no managers will be discovered")
        raise
    return [cls() for cls in _REGISTRY]
