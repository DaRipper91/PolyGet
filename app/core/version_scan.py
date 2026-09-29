"""Cross-manager newest-version scan core logic."""

import asyncio
import json
import re
from typing import Any

from packaging.version import Version

from app.core.manager import PackageManager, discover_managers
from app.core.ignore_store import IgnoreStore


# ──────────────────────────────────────────────────────────────────────────────
# Version normalization / comparison (per-ecosystem)
# ──────────────────────────────────────────────────────────────────────────────

_JS_MANAGERS = {"NPM", "pnpm", "Yarn"}  # managers with semver versions
_SYSTEM_MANAGERS = {"Pacman", "DNF", "APT"}  # managers with pkgver-pkgrel/epoch versions


def _normalize_name(name: str) -> str:
    """Normalize package name for cross-manager matching.

    Conservative: lowercase + strip common distro prefixes. No aliases in v1.
    """
    n = name.lower().strip()
    for prefix in ("python-", "node-", "perl-", "ruby-", "lib"):
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    return n


def _parse_semver(version: str) -> Version | None:
    """Parse a semver version string using packaging.version.Version.

    Returns None on parse failure (caller should fall back to string equality).
    """
    if not version or version == "unknown":
        return None
    try:
        return Version(version)
    except Exception:
        return None


def _parse_system_version(version: str) -> tuple[int, ...] | None:
    """Parse a distro version string (pkgver-pkgrel) into comparable components.

    Strips epoch (the leading N: in dpkg) and pkgrel (the -N suffix in pacman/dnf).
    Returns a tuple of ints (major, minor, patch, ...) for component-wise comparison,
    or None if parsing fails.
    """
    if not version or version == "unknown":
        return None
    # Strip dpkg epoch (e.g. "1:2.0-1" -> "2.0-1")
    if ":" in version:
        version = version.split(":", 1)[1]
    # Strip pkgrel (e.g. "5.0.4-1" -> "5.0.4")
    if "-" in version:
        version = version.rsplit("-", 1)[0]
    # Split into numeric components
    parts = re.split(r"[.\-]", version)
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            # Non-numeric component (e.g. "rc1", "beta") — bail to string compare
            return None
    return tuple(nums) if nums else None


def _version_greater(manager_name: str, v1: str, v2: str) -> bool | None:
    """Return True if v1 > v2 for the given manager's ecosystem.

    Returns None if comparison is not possible (unparseable versions),
    in which case the caller should treat versions as incomparable.
    """
    if manager_name in _JS_MANAGERS:
        p1 = _parse_semver(v1)
        p2 = _parse_semver(v2)
        if p1 is not None and p2 is not None:
            return p1 > p2
        return None
    if manager_name in _SYSTEM_MANAGERS:
        p1 = _parse_system_version(v1)
        p2 = _parse_system_version(v2)
        if p1 is not None and p2 is not None:
            return p1 > p2
        return None
    # Unknown manager — conservative: don't guess
    return None


def _best_version(versions: dict[str, str]) -> tuple[str | None, str | None]:
    """Return (manager_with_best_version, best_version) from a {manager: version} mapping.

    Returns (None, None) if no comparable versions.
    """
    best_mgr = None
    best_ver = None
    for mgr, ver in versions.items():
        if best_ver is None:
            best_mgr, best_ver = mgr, ver
            continue
        cmp = _version_greater(mgr, ver, best_ver)
        if cmp is True:
            best_mgr, best_ver = mgr, ver
    return best_mgr, best_ver


# ──────────────────────────────────────────────────────────────────────────────
# Core scan function
# ──────────────────────────────────────────────────────────────────────────────

async def cross_manager_newest(
    managers: list[PackageManager] | None = None,
    manager_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Scan installed packages across managers and find cross-manager version differences.

    Args:
        managers: Optional list of managers to scan. Defaults to all discovered.
        manager_filter: Optional list of manager names to restrict scan to.

    Returns:
        Dict with keys:
        - "suggestions": list of suggestion dicts (see below)
        - "managers": per-manager status {ok, error?, versions?}
    """
    if managers is None:
        managers = discover_managers()

    if manager_filter:
        filter_set = set(manager_filter)
        managers = [m for m in managers if m.name in filter_set]

    # Gather installed versions per manager (reusing _gather_per_manager pattern)
    results: dict[str, dict[str, Any]] = {}
    awaitable_map = {m.name: m.list_installed_versions() for m in managers}

    for name, coro in awaitable_map.items():
        try:
            versions = await coro
            results[name] = {"ok": True, "versions": versions}
        except NotImplementedError:
            results[name] = {"ok": True, "versions": {}}
        except Exception as e:
            results[name] = {"ok": False, "error": str(e), "versions": {}}

    # Group by normalized name across managers
    groups: dict[str, dict[str, str]] = {}  # norm_name -> {manager: version}
    for mgr_name, res in results.items():
        if not res.get("ok"):
            continue
        for pkg_name, version in res.get("versions", {}).items():
            norm = _normalize_name(pkg_name)
            groups.setdefault(norm, {})[mgr_name] = version

    # Build suggestions: packages present on ≥2 managers with a strictly higher version elsewhere
    suggestions = []
    for norm_name, versions_by_mgr in groups.items():
        if len(versions_by_mgr) < 2:
            continue
        best_mgr, best_ver = _best_version(versions_by_mgr)
        if best_mgr is None:
            continue
        for mgr, ver in versions_by_mgr.items():
            if mgr == best_mgr:
                continue
            cmp = _version_greater(mgr, best_ver, ver)
            if cmp is True:
                suggestions.append({
                    "package": norm_name,
                    "installed": {m: versions_by_mgr[m] for m in versions_by_mgr},
                    "newest": {"manager": best_mgr, "version": best_ver},
                    "note": None,
                })
                break  # one suggestion per package (the best one)

    return {
        "suggestions": suggestions,
        "managers": {name: res for name, res in results.items()},
    }


async def _scan_with_ignore(
    managers: list[PackageManager] | None = None,
    manager_filter: list[str] | None = None,
    include_ignored: bool = False,
) -> dict[str, Any]:
    """Internal: run cross_manager_newest and filter by IgnoreStore (per-manager)."""
    result = await cross_manager_newest(managers, manager_filter)
    if include_ignored:
        return result

    store = IgnoreStore()
    filtered = []
    for s in result["suggestions"]:
        # A suggestion is ignored if ALL its installed versions are ignored per-manager
        ignored = all(
            store.is_ignored(mgr, s["package"]) for mgr in s["installed"]
        )
        if not ignored:
            filtered.append(s)
    result["suggestions"] = filtered
    return result


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry (called from app/cli.py)
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_newest(
    args: Any,
    managers: list[PackageManager],
) -> tuple[int, dict[str, Any]]:
    """CLI entry for `run.py newest`. Returns (exit_code, payload)."""
    include_ignored = getattr(args, "include_ignored", False)
    manager_filter = getattr(args, "manager", None)

    result = await _scan_with_ignore(
        managers=managers,
        manager_filter=manager_filter,
        include_ignored=include_ignored,
    )

    # Exit code: 0 if ≥1 manager succeeded, 2 if zero succeeded
    any_ok = any(res.get("ok") for res in result["managers"].values())
    exit_code = 0 if any_ok else 2
    return exit_code, result