"""Package manager driver for Fisher (fish shell plugin manager)."""

import os
import shutil
from pathlib import Path
from typing import Any
from app.core.manager import DriverError, PackageManager, register_manager


def _fish_config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "fish"


def _fisher(subcommand: str, packages: list[str]) -> list[str]:
    # Fisher is a fish function, not a binary, so it runs through `fish -c`. `subcommand` is always a
    # literal from this module; package names go after `--` and reach fisher as $argv, never as script text.
    return ["fish", "-c", f"fisher {subcommand} $argv", "--"] + packages


@register_manager
class FisherManager(PackageManager):
    """Fish plugins installed with Fisher. Package names are what `fish_plugins` lists, e.g. `jorgebucaran/nvm.fish`.

    Fisher has no "what is outdated" query (plugins are git repos with no recorded commit), so
    update checks are unsupported rather than guessed; `fisher update` still works when asked for.
    """

    name: str = "Fisher"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("fish") is not None and (_fish_config_dir() / "functions" / "fisher.fish").is_file()

    async def list_installed(self) -> list[str]:
        # Fisher records every installed plugin, one per line, in fish_plugins.
        path = _fish_config_dir() / "fish_plugins"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError as e:
            raise DriverError(f"{self.name} installed-plugin query failed: {e}") from e
        return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]

    async def check_updates(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Fisher has no outdated-plugin query; run an update to refresh all plugins")

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        return _fisher("update", packages or [])

    def get_install_command(self, package: str) -> list[str]:
        return _fisher("install", [package])

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return _fisher("remove", packages)
