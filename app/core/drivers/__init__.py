"""Package manager driver implementations.

Importing this module registers all available package manager drivers.
"""

from app.core.drivers.dnf import DnfManager
from app.core.drivers.flatpak import FlatpakManager
from app.core.drivers.pipx import PipxManager
from app.core.drivers.npm import NpmManager
from app.core.drivers.cargo import CargoManager
