"""Package manager driver for uv (Python tools installed with `uv tool install`)."""

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any
from packaging.version import InvalidVersion, Version
from app.core.janitor import dir_size, target
from app.core.manager import DriverError, PackageManager, fetch_json, register_manager, run_capture

try:
    import tomllib
except ImportError:  # Python 3.10 has no tomllib; _has_local_source falls back to scanning the text
    tomllib = None

# A tool installed from one of these has no meaningful PyPI "latest": a same-named PyPI project would be an
# unrelated package, and the update could never clear. `editable` is what `uv tool install -e <dir>` records.
_LOCAL_SOURCE_KEYS = ("directory", "path", "git", "url", "editable")
_LOCAL_SOURCE_RE = re.compile(r"(?<![\w-])(?:directory|path|git|url|editable)\s*=")


def _requirements_block(text: str) -> str:
    """The text of the `requirements = [...]` array, however many lines it spans (strings are skipped)."""
    match = re.search(r"^requirements\s*=\s*\[", text, re.MULTILINE)
    if not match:
        return ""
    depth, quote, i = 0, "", match.end() - 1
    while i < len(text):
        ch = text[i]
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[match.end():i]
        i += 1
    return text[match.end():]


def _has_local_source(receipt: str) -> bool:
    """True if a tool's `uv-receipt.toml` says it was installed from a directory, path, git repo, or URL."""
    if tomllib is not None:
        try:
            requirements = tomllib.loads(receipt).get("tool", {}).get("requirements", [])
        except tomllib.TOMLDecodeError:
            return False
        return any(isinstance(r, dict) and any(k in r for k in _LOCAL_SOURCE_KEYS) for r in requirements)
    return bool(_LOCAL_SOURCE_RE.search(_requirements_block(receipt)))


def _is_newer(latest: str, current: str) -> bool:
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return latest != current


@register_manager
class UvManager(PackageManager):
    """Package manager driver for uv tools.

    uv has no `outdated` or `search` command for tools, so updates are checked against
    PyPI directly. Search is left unsupported on purpose: the Pipx driver already searches
    PyPI, and a second copy of the same results would only add noise.
    """

    name: str = "uv"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("uv") is not None

    async def list_installed_versions(self) -> dict[str, str]:
        out = await run_capture(["uv", "tool", "list"], label=f"{self.name} installed-package query")
        versions = {}
        for line in out.splitlines():
            parts = line.split()
            # "agentdeck v0.1.0" per tool; its executables follow as "- agentdeck".
            if len(parts) == 2 and not line.startswith("-") and parts[1].startswith("v"):
                versions[parts[0]] = parts[1][1:]
        return versions

    async def list_installed(self) -> list[str]:
        return list(await self.list_installed_versions())

    async def _local_source_tools(self, tools: list[str]) -> set[str]:
        """Tools installed from a local or VCS source, read from each tool's receipt.

        If the tool directory or a receipt cannot be read the tool is simply not excluded: the old
        behaviour (a PyPI lookup) is kept rather than hiding a tool whose source is unknown.
        """
        try:
            tool_dir = Path((await run_capture(["uv", "tool", "dir"], label=f"{self.name} tool dir")).strip())
        except DriverError:
            return set()

        def read(tool: str) -> bool:
            try:
                return _has_local_source((tool_dir / tool / "uv-receipt.toml").read_text(encoding="utf-8"))
            except OSError:
                return False

        flags = await asyncio.gather(*(asyncio.to_thread(read, t) for t in tools))
        return {t for t, local in zip(tools, flags) if local}

    async def check_updates(self) -> list[dict[str, Any]]:
        tools = await self.list_installed_versions()
        local = await self._local_source_tools(list(tools))
        tools = {t: v for t, v in tools.items() if t not in local}
        if not tools:
            return []

        async def latest(tool: str) -> str:
            data = await fetch_json(f"https://pypi.org/pypi/{tool}/json", label=f"{self.name} {tool} lookup")
            return str(data["info"]["version"])

        results = await asyncio.gather(*(latest(t) for t in tools), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        # One flaky lookup must not hide the rest, but if every lookup died the registry is
        # unreachable and "no updates" would be a false clean bill.
        if failures and len(failures) == len(results):
            raise DriverError(f"{self.name} update check failed: {failures[0]}")
        return [
            {"name": tool, "current": current, "new": new}
            for (tool, current), new in zip(tools.items(), results)
            if not isinstance(new, Exception) and _is_newer(new, current)
        ]

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["uv", "tool", "upgrade"] + packages
        return ["uv", "tool", "upgrade", "--all"]

    async def get_cleanup_targets(self) -> list[dict[str, Any]]:
        cache = (await run_capture(["uv", "cache", "dir"], label=f"{self.name} cache query")).strip()
        size = await dir_size(Path(cache)) if cache else 0
        if not size:
            return []
        return [target(self.name, "cache", "Package cache", ["uv", "cache", "clean"], size,
                       detail="wheels and sources uv downloads again on demand")]

    def get_install_command(self, package: str) -> list[str]:
        return ["uv", "tool", "install", package]

    def get_remove_command(self, packages: list[str]) -> list[str]:
        return ["uv", "tool", "uninstall"] + packages
