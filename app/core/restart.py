"""Detect whether the machine needs a reboot after upgrades (kernel, glibc, systemd, firmware...)."""

import asyncio
import os
from pathlib import Path
from typing import Any

from app.core.distro import get_reboot_check_command, replaces_running_kernel
from app.core.manager import describe_error

_MODULES_DIR = Path("/usr/lib/modules")
_DEBIAN_FLAG = Path("/run/reboot-required")


def _result(needed: bool | None, method: str, reasons: list[str] | None = None) -> dict[str, Any]:
    return {"needed": needed, "method": method, "reasons": reasons or []}


def _running_kernel_check() -> dict[str, Any] | None:
    """The running kernel's modules are gone once a kernel upgrade replaced it (how Arch-family
    systems, CachyOS included, signal "reboot to use the new kernel"). None when it can't tell."""
    if not _MODULES_DIR.is_dir():
        return None
    release = os.uname().release
    if (_MODULES_DIR / release).is_dir():
        return _result(False, "kernel modules")
    installed = sorted(p.name for p in _MODULES_DIR.iterdir() if p.is_dir())
    return _result(True, "kernel modules",
                   [f"running kernel {release} was replaced (installed: {', '.join(installed) or 'none'})"])


async def _distro_check(argv: list[str]) -> dict[str, Any] | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except Exception:
        return None  # tool missing or hung: fall back to the generic checks
    text = (stdout + stderr).decode(errors="ignore")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # A missing plugin also exits 1 ("No such command"), so status alone isn't trusted.
    if any(marker in text for marker in ("No such command", "Unknown argument", "unrecognized")):
        return None
    if proc.returncode == 0:
        return _result(False, " ".join(argv))
    if proc.returncode == 1:
        # dnf lists what changed as "  * kernel" bullets under a header line.
        reasons = [line.lstrip("* ").strip() for line in lines if line.startswith("*")]
        return _result(True, " ".join(argv), reasons or lines[:1])
    return None


async def check_restart_needed() -> dict[str, Any]:
    """{"needed": True/False/None, "method": ..., "reasons": [...]}. None means PolyGet couldn't tell."""
    argv = get_reboot_check_command()
    if argv:
        result = await _distro_check(argv)
        if result is not None:
            return result
    if _DEBIAN_FLAG.exists():
        pkgs_file = _DEBIAN_FLAG.with_suffix(".pkgs")
        try:
            pkgs = sorted(set(pkgs_file.read_text().split())) if pkgs_file.exists() else []
        except OSError as e:
            pkgs = [f"(could not read {pkgs_file}: {describe_error(e)})"]
        return _result(True, str(_DEBIAN_FLAG), [f"updated: {', '.join(pkgs)}"] if pkgs else [])
    return (_running_kernel_check() if replaces_running_kernel() else None) or _result(None, "none available")
