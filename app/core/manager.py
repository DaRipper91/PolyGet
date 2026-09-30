"""Base package manager interface and discovery utilities."""

import shutil
from typing import Type, Any


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


class PackageManager:
    """Base class defining the interface for all package manager drivers."""

    name: str = "Base"
    category: str = "Base"

    def is_available(self) -> bool:
        """Check if the package manager's binary is available in the system PATH.

        Returns:
            bool: True if available, False otherwise.
        """
        raise NotImplementedError("Subclasses must implement is_available()")

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
        import app.core.drivers
    except ImportError:
        pass

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
        import app.core.drivers
    except ImportError:
        pass
    return [cls() for cls in _REGISTRY]
