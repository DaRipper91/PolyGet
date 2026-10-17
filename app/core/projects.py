"""Helpers for per-project package managers (Bundler, Gradle) that scan tracked directories.

These tools have no global package list, so their drivers read the project directories the
user registered in settings. Update names encode the owning project ("rake @ /path/app") so
the synchronous command builders know where to run.
"""

from pathlib import Path
from app.core.manager import DriverError
from app.core.settings_store import get_settings

_SEP = " @ "


def tracked_projects(marker: str) -> list[Path]:
    """Return tracked directories that actually contain `marker` (e.g. 'Gemfile')."""
    return [Path(d) for d in get_settings().get_project_dirs() if (Path(d) / marker).is_file()]


def make_target(item: str, project: Path) -> str:
    return f"{item}{_SEP}{project}"


def split_target(name: str) -> tuple[str, Path]:
    item, sep, project = name.partition(_SEP)
    if not sep or not item or not project:
        raise DriverError(f"'{name}' is not a project-scoped package (expected 'name{_SEP}/project/dir')")
    return item, Path(project)


def resolve_single_project(packages: list[str] | None, marker: str, manager: str) -> tuple[Path, list[str]]:
    """Resolve the one project an upgrade applies to, plus its package names.

    A command is a single argv, so it can only act in one project. Refusing an ambiguous
    selection beats silently upgrading just one of several projects.
    """
    if packages:
        pairs = [split_target(p) for p in packages]
        projects = {proj for _, proj in pairs}
        if len(projects) > 1:
            raise DriverError(f"{manager} upgrades one project at a time; the selection spans {len(projects)}")
        return pairs[0][1], [item for item, _ in pairs]
    projects = tracked_projects(marker)
    if len(projects) != 1:
        raise DriverError(
            f"{manager} upgrades one project at a time; select packages from a single project "
            f"({len(projects)} tracked)"
        )
    return projects[0], []
