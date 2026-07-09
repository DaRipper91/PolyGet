"""Detect the running system's distro family for choosing correct package-manager commands."""

import functools
import re

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

@functools.lru_cache(maxsize=1)
def get_distro_family() -> str:
    """Return a normalized distro family string by reading /etc/os-release.

    Checks ID first, then falls back to scanning ID_LIKE for a known family.
    Returns "unknown" if nothing matches.
    """
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return "unknown"

    fields = {}
    for match in re.finditer(r'^(\w+)=(.*)$', content, re.MULTILINE):
        key = match.group(1)
        val = match.group(2).strip().strip('"').strip("'")
        fields[key] = val

    id_val = fields.get("ID", "").lower()
    id_like = fields.get("ID_LIKE", "").lower()

    if id_val in _FAMILY_MAP:
        return _FAMILY_MAP[id_val]

    for token in id_like.split():
        if token in _FAMILY_MAP:
            return _FAMILY_MAP[token]

    return "unknown"
