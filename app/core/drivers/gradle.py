"""Package manager driver for Gradle (wrapper versions in tracked project directories)."""

import re
import shutil
from pathlib import Path
from typing import Any
from app.core.manager import DriverError, PackageManager, describe_error, fetch_json, register_manager
from app.core.projects import make_target, resolve_single_project, tracked_projects

_WRAPPER_PROPS = Path("gradle") / "wrapper" / "gradle-wrapper.properties"
_DIST_RE = re.compile(r"gradle-([\w.\-]+?)-(?:bin|all)\.zip")


def _wrapper_projects() -> list[Path]:
    return [p for p in tracked_projects("gradlew") if (p / _WRAPPER_PROPS).is_file()]


def _wrapper_version(project: Path) -> str:
    try:
        text = (project / _WRAPPER_PROPS).read_text(encoding="utf-8")
    except OSError as e:
        raise DriverError(f"Gradle could not read the wrapper in {project}: {describe_error(e)}") from e
    match = _DIST_RE.search(text)
    if not match:
        raise DriverError(f"Gradle could not find a distributionUrl version in {project}")
    return match.group(1)


@register_manager
class GradleManager(PackageManager):
    """Package manager driver for Gradle.

    Gradle has no built-in dependency-update command, but it does have a real built-in
    upgrade path: the wrapper. This driver tracks each registered project's wrapper version
    against the current Gradle release and upgrades it with `gradlew wrapper`. Like Bundler
    it only reports as available once a project with a wrapper is tracked.
    """

    name: str = "Gradle"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("gradle") is not None and bool(_wrapper_projects())

    async def list_installed_versions(self) -> dict[str, str]:
        return {make_target("gradle wrapper", p): _wrapper_version(p) for p in _wrapper_projects()}

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        installed = await self.list_installed_versions()
        if not installed:
            return []
        data = await fetch_json("https://services.gradle.org/versions/current", label=f"{self.name} version lookup")
        latest = str(data["version"])
        return [
            {"name": name, "current": current, "new": latest}
            for name, current in installed.items() if current != latest
        ]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        project, _ = resolve_single_project(packages, "gradlew", self.name)
        return [str(project / "gradlew"), "-p", str(project), "wrapper", "--gradle-version", "latest"]
