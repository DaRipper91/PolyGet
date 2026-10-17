"""Detect the machine's CPU architecture, normalized so aliases compare equal."""

import functools
import platform
import sys

# The same CPU is reported under different names by different systems: Linux says
# "aarch64" where macOS says "arm64"; Debian says "amd64" where the kernel says "x86_64".
_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "x64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "aarch64_be": "aarch64_be",
    "armv8b": "aarch64_be",
}


def normalize_arch(value: str) -> str:
    """Map an architecture name to its canonical spelling (unknown names pass through lowercased)."""
    name = value.strip().lower()
    return _ALIASES.get(name, name)


@functools.lru_cache(maxsize=1)
def get_machine_arch() -> str:
    """Return the canonical CPU architecture of this machine, or "unknown" if it cannot be read."""
    return normalize_arch(platform.machine()) or "unknown"


def describe_system() -> dict[str, str]:
    """Summarize what PolyGet detected about this machine, for display."""
    from app.core.distro import get_distro_family

    return {"arch": get_machine_arch(), "distro_family": get_distro_family(), "platform": sys.platform}
