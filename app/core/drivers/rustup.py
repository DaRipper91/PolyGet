"""Package manager driver for rustup (Rust toolchains: stable, nightly, pinned versions)."""

import re
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager, run_capture

# `rustup check` prints one line per toolchain, plus one for rustup itself:
#   stable-x86_64-unknown-linux-gnu - Update available : 1.97.0 (2d8144b78 2026-07-07) -> 1.99.1 (58cf8f9c3 2026-10-13)
#   nightly-x86_64-unknown-linux-gnu - Up to date : 1.100.0-nightly (abc 2026-10-16)
# rustup 1.29 writes "- update available: X -> Y" (lowercase, no space before the colon) and
# exits 100 when anything is outdated.
_CHECK_RE = re.compile(r"^(\S+) - update available\s*: (\S+).*? -> (\S+)", re.IGNORECASE)


def _parse_check(output: str) -> list[dict[str, Any]]:
    updates = []
    for line in output.splitlines():
        m = _CHECK_RE.match(line.strip())
        # rustup's own line is skipped: distro-packaged rustup refuses `rustup self update`,
        # so it is updated by the system package manager instead.
        if m and m.group(1) != "rustup":
            updates.append({"name": m.group(1), "current": m.group(2), "new": m.group(3)})
    return updates


@register_manager
class RustupManager(PackageManager):
    """Rust toolchains managed by rustup. Packages are toolchain names, e.g. `stable-x86_64-unknown-linux-gnu`."""

    name: str = "Rustup"
    category: str = "Language/Dev"
    changelog_url_template = "https://blog.rust-lang.org/releases/"

    def is_available(self) -> bool:
        return shutil.which("rustup") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        out = await run_capture(["rustup", "check"], label=f"{self.name} update check", timeout=60.0,
                                ok_codes=(0, 100))
        return _parse_check(out)

    async def list_installed(self) -> list[str]:
        out = await run_capture(["rustup", "toolchain", "list"], label=f"{self.name} installed-toolchain query")
        # Lines look like "stable-x86_64-unknown-linux-gnu (active, default)".
        return [line.split()[0] for line in out.splitlines() if line.strip() and "no installed toolchains" not in line]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        # `--no-self-update` keeps a toolchain update from also replacing rustup itself.
        return ["rustup", "update", "--no-self-update"] + (packages or [])

    def get_install_command(self, package: str) -> list[str]:
        return ["rustup", "toolchain", "install", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["rustup", "toolchain", "uninstall"] + packages
