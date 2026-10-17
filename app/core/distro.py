"""Detect the running system's distro family for choosing correct package-manager commands."""

import functools
import re
import sys

_FAMILY_MAP = {
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "arch": "arch",
    "cachyos": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "debian": "debian",
    "ubuntu": "debian",
    "suse": "suse",
    "opensuse": "suse",
    "alpine": "alpine",
    "void": "void",
    "nixos": "nix",
}

def _os_release() -> dict[str, str]:
    """Parse /etc/os-release into a dict; empty when the file is missing or unreadable."""
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return {}

    fields = {}
    for match in re.finditer(r'^(\w+)=(.*)$', content, re.MULTILINE):
        key = match.group(1)
        val = match.group(2).strip().strip('"').strip("'")
        fields[key] = val
    return fields


@functools.lru_cache(maxsize=1)
def get_distro_family() -> str:
    """Return a normalized distro family string by reading /etc/os-release.

    Checks ID first, then falls back to scanning ID_LIKE for a known family.
    Returns "unknown" if nothing matches.
    """
    if sys.platform == "darwin":
        return "macos"
    fields = _os_release()
    if not fields:
        return "unknown"

    id_val = fields.get("ID", "").lower()
    id_like = fields.get("ID_LIKE", "").lower()

    if id_val in _FAMILY_MAP:
        return _FAMILY_MAP[id_val]

    for token in id_like.split():
        if token in _FAMILY_MAP:
            return _FAMILY_MAP[token]

    return "unknown"


# The driver that owns the distro's own packages (and so AppStream "package" components).
_SYSTEM_MANAGER = {"fedora": "DNF", "arch": "Pacman", "debian": "APT"}


def get_system_manager_name() -> str | None:
    """Name of the driver for this distro's native packages, or None if PolyGet has none."""
    return _SYSTEM_MANAGER.get(get_distro_family())


@functools.lru_cache(maxsize=1)
def get_distro_name() -> str:
    """Return the human-readable distro name (PRETTY_NAME, else NAME), or "" if unknown."""
    if sys.platform == "darwin":
        return "macOS"
    fields = _os_release()
    return fields.get("PRETTY_NAME") or fields.get("NAME", "")
