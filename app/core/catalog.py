"""Loads the static manager catalog for the Manager Store, independent of installed drivers."""

import shutil
from dataclasses import dataclass, field
from importlib import resources
import yaml

from app.core.manager import discover_managers
from app.core.distro import get_distro_family

@dataclass
class CatalogEntry:
    id: str
    name: str
    category: str
    description: str
    icon: str
    binary: str
    has_driver: bool
    self_install: dict[str, list[str]] = field(default_factory=dict)
    installed: bool = False

    def get_self_install_command(self) -> list[str] | None:
        """Return the install command for the current distro family, if known."""
        family = get_distro_family()
        return self.self_install.get(family)

def _binary_present(binary: str) -> bool:
    return shutil.which(binary) is not None

def load_catalog() -> list[CatalogEntry]:
    """Load the static manager catalog and annotate each entry with installed status."""
    with resources.files("app.core.data").joinpath("manager_catalog.yaml").open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []

    active_names = {mgr.name.lower() for mgr in discover_managers()}
    entries = []
    for item in raw:
        entry = CatalogEntry(**item)
        # Marked as installed if either the driver registry is active or the binary itself is present on the host
        entry.installed = (
            entry.name.lower() in active_names
            or entry.id.lower() in active_names
            or _binary_present(entry.binary)
        )
        entries.append(entry)
    return entries
