"""Package manager driver for Distrobox (host-integrated containers of other distros)."""

import re
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager, run_capture


@register_manager
class DistroboxManager(PackageManager):
    """Package manager driver for Distrobox.

    The unit managed here is the container, not a package: "installed" lists containers
    (version = image), upgrade runs each container's own package manager, and "install"
    creates a container from an image.
    """

    name: str = "Distrobox"
    category: str = "Universal"

    def is_available(self) -> bool:
        return shutil.which("distrobox") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        out = await run_capture(["distrobox", "list", "--no-color"], label=f"{self.name} container query", timeout=30.0)
        containers = {}
        # Table: "ID | NAME | STATUS | IMAGE" with a header row.
        for line in out.splitlines()[1:]:
            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 4 and cols[1]:
                containers[cols[1]] = cols[3]
        return containers

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def check_updates(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Distrobox cannot report outdated packages inside containers")

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return ["distrobox", "upgrade"] + (packages if packages else ["--all"])

    def get_install_command(self, package: str) -> list[str]:
        container = re.sub(r"[^\w.\-]", "-", package.rsplit("/", 1)[-1].split(":")[0]) or "container"
        return ["distrobox", "create", "--yes", "--name", container, "--image", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["distrobox", "rm", "--force"] + packages
