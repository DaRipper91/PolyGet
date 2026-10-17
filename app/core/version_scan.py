"""Cross-manager newest-version scan core logic."""

import re
from typing import Any

from packaging.version import Version

from app.core.manager import DriverError, PackageManager, describe_error, discover_managers
from app.core.ignore_store import IgnoreStore
from app.core.settings_store import get_settings


# ──────────────────────────────────────────────────────────────────────────────
# Version normalization / comparison (per-ecosystem)
# ──────────────────────────────────────────────────────────────────────────────

_JS_MANAGERS = {"NPM", "pnpm", "Yarn"}  # managers with semver versions
_SYSTEM_MANAGERS = {"Pacman", "DNF", "APT"}  # managers with pkgver-pkgrel/epoch versions


# Managers whose versions are a *system-wide distribution copy* of a package that a
# language-runtime manager may also provide. Comparing these against a runtime manager
# is meaningful (pipx's uvicorn vs the distro's python-uvicorn really are the same
# software) even though the version grammars differ.
_DISTRO_MANAGERS = _SYSTEM_MANAGERS

# Language-runtime managers, grouped by ecosystem. Two different runtimes are never
# comparable: a gem named `yaml` and a PyPI package named `yaml` are unrelated
# software that merely share a name, so ranking them against each other would
# produce a confident, wrong suggestion.
_RUNTIME_ECOSYSTEMS: dict[str, str] = {
    "NPM": "js", "pnpm": "js", "Yarn": "js",
    "Pipx": "python", "Poetry": "python",
    "Cargo": "rust",
    "RubyGems": "ruby",
    "Dart Pub": "dart", "Hex": "elixir", "Julia": "julia", "cpanm": "perl",
}

# Managers with no meaningful cross-ecosystem comparison. Flatpak versions are app
# versions chosen by the packager, not upstream semver, and every runtime ecosystem
# here is distinct, so a Flatpak app id will never legitimately rank against another
# manager's version. The members are still reported (their versions are scanned and
# listed) — they just never produce a suggestion.
_UNCOMPARABLE_MANAGERS = {"Flatpak"}

# Version strings that must never be compared. RubyGems reports interpreter-bundled
# gems as `default: 0.4.0` — that version tracks the Ruby stdlib, is not separately
# installable, and routinely differs from the distro package of the same name.
_UNCOMPARABLE_VERSION_RE = re.compile(
    r"^\s*(default\s*:|unknown\b|not installed|none\b|\(none\))", re.IGNORECASE
)


def _is_comparable_version(version: str) -> bool:
    """True when a version string is a real, rankable release number."""
    if not version or not version.strip():
        return False
    if _UNCOMPARABLE_VERSION_RE.match(version):
        return False
    return True



# Manager pairs whose version numbers are NOT reliably comparable even though both
# sides are legitimately reporting the same package name. Each entry is here because
# of observed data, not theory — see the comment on each for the live overlap.
_UNTRUSTED_PAIRS: set[frozenset[str]] = {
    # Observed on CachyOS: 65 RubyGems<->Pacman overlaps, of which exactly one showed a
    # version difference — google-protobuf (gem 4.36.1 vs Arch 36.1), a false positive.
    # RubyGems' Gem::Version scheme and distro pkgver do not track the same counter.
    frozenset({"RubyGems", "Pacman"}),
    frozenset({"RubyGems", "DNF"}),
    frozenset({"RubyGems", "APT"}),
    # npm/pnpm/yarn all reach the same registry, so a differing version between them is a
    # shadowed global install, not a newer release elsewhere. Marked rather than hidden
    # because it is still worth showing (with a caveat).
    frozenset({"NPM", "pnpm"}),
    frozenset({"NPM", "Yarn"}),
    frozenset({"pnpm", "Yarn"}),
}


def _untrusted_pairs_from_settings(settings: Any | None) -> set[frozenset[str]]:
    """User-supplied extra untrusted pairs, as a set of frozensets."""
    if settings is None:
        return set()
    try:
        raw = settings.get("version_scan.untrusted_pairs", []) or []
    except Exception:
        return set()
    pairs = set()
    for entry in raw:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            pairs.add(frozenset((str(entry[0]), str(entry[1]))))
    return pairs


def _comparators(a: str, b: str) -> tuple[str, str] | None:
    """Return the comparator pair to use for managers `a` and `b`, or None if the
    two are not legitimately comparable.

    Same runtime ecosystem, or a distro manager against any runtime (the system copy
    of a package the runtime also ships), are comparable. Two *different* runtime
    ecosystems are not.
    """
    if a == b:
        # Same manager: use its own ecosystem's comparator.
        return a, a

    if a in _UNCOMPARABLE_MANAGERS or b in _UNCOMPARABLE_MANAGERS:
        return None

    a_distro = a in _DISTRO_MANAGERS
    b_distro = b in _DISTRO_MANAGERS

    if a_distro or b_distro:
        # Distro-vs-runtime (or distro-vs-distro). Route through the *runtime's*
        # comparator so a pipx semver isn't ranked with a dpkg epoch grammar.
        runtime = b if a_distro else a
        if runtime in _RUNTIME_ECOSYSTEMS:
            return runtime, runtime
        # distro vs distro, or distro vs a manager with no known runtime ecosystem
        return a, a if not a_distro else b

    ea = _RUNTIME_ECOSYSTEMS.get(a)
    eb = _RUNTIME_ECOSYSTEMS.get(b)
    if ea is None or eb is None or ea != eb:
        return None
    return a, b


def _pair_comparable(a: str, b: str, untrusted: set[frozenset[str]] | None = None) -> bool:
    """True when a pair may be compared at all: same scheme *and* not untrusted."""
    if untrusted and frozenset((a, b)) in untrusted:
        return False
    if frozenset((a, b)) in _UNTRUSTED_PAIRS:
        return False
    return _comparators(a, b) is not None


def _normalize_name(name: str) -> str:
    """Normalize package name for cross-manager matching.

    Conservative: lowercase + strip common distro prefixes. No aliases in v1.
    """
    n = name.lower().strip()
    for prefix in ("python-", "node-", "perl-", "ruby-"):
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    else:
        # Only strip a bare "lib" prefix when it is followed by a separator
        # or a digit, so that compound names like "libreoffice" are not
        # mangled into "reoffice".  Library packages in Debian/Ubuntu are
        # typically "libfoo", "libfoo-dev", "libfoo1" etc.
        if n.startswith("lib") and len(n) > 3 and (n[3] in "-_0123456789"):
            # Strip "lib" plus a following separator (but keep digits as part of name)
            if n[3] in "-_":
                n = n[4:]
            else:
                n = n[3:]
    return n


def _parse_semver(version: str) -> Version | None:
    """Parse a semver version string.

    Tolerates a leading `v` (Cargo reports `v4.2.0`) and PEP 440 pre-release
    spellings that `packaging` understands (`1.0.0rc1`) as well as semver's
    (`1.0.0-rc.1`). Returns None on parse failure.
    """
    if not _is_comparable_version(version):
        return None
    candidate = version.strip()
    if candidate[:1] in ("v", "V"):
        candidate = candidate[1:]
    # Build metadata is not ordered per the semver spec; drop it.
    candidate = candidate.split("+", 1)[0]
    try:
        return Version(candidate)
    except Exception:
        return None


def _parse_system_version(version: str) -> tuple[int, ...] | None:
    """Parse a distro version string (pkgver-pkgrel) into comparable components.

    Strips epoch (the leading N: in dpkg) and pkgrel (the -N suffix in pacman/dnf).
    Returns a tuple of ints (major, minor, patch, ...) for component-wise comparison,
    or None if parsing fails.
    """
    if not _is_comparable_version(version):
        return None
    if ":" in version:
        version = version.split(":", 1)[1]
    # Strip pkgrel (e.g. -2) but preserve pre-release markers (e.g. -rc1).
    if "-" in version:
        suffix = version.rsplit("-", 1)[1]
        if suffix.isdigit():
            version = version.rsplit("-", 1)[0]
    parts = re.split(r"[.\-]", version)
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            # Non-numeric component (e.g. "rc1", "beta") — bail to string compare
            return None
    return tuple(nums) if nums else None


def _parse_version_for(manager_name: str, version: str, is_system: bool = False):
    """Parse *version* using the parser appropriate for *manager_name*'s ecosystem.

    When a system-manager version is being parsed with a runtime grammar (cross-
    ecosystem comparison), strip the pkgrel first so "0.53.0-1" is treated as
    "0.53.0" rather than as a pre-release.
    """
    if is_system and manager_name not in _SYSTEM_MANAGERS and "-" in version:
        # Cross-ecosystem: system version parsed with runtime grammar — strip pkgrel
        version = version.rsplit("-", 1)[0]
    if manager_name in _SYSTEM_MANAGERS:
        return _parse_system_version(version)
    return _parse_semver(version)


def _comparator_for_pair(mgr1: str, mgr2: str) -> str | None:
    """Return the manager whose parser should be used for BOTH versions in this pair.

    For same-ecosystem pairs, uses that ecosystem's parser. For distro-vs-runtime
    pairs, uses the runtime's parser (the distro version is parsed with the
    runtime's grammar, which may fail — in which case the pair is incomparable).
    Returns None if the pair is not comparable.
    """
    result = _comparators(mgr1, mgr2)
    if result is None:
        return None
    # result is (a, b) — both should use the same parser; pick the first.
    return result[0]


def _version_greater(mgr1: str, v1: str, mgr2: str, v2: str) -> bool | None:
    """Return True if v1 (from mgr1) > v2 (from mgr2).

    Both versions are parsed with the comparator determined by the pair (via
    _comparators), so cross-ecosystem pairs use the runtime's grammar for both
    sides. System-manager versions have their pkgrel stripped before parsing
    with a runtime grammar. Returns None when either version is unparseable or
    types differ.
    """
    comp = _comparator_for_pair(mgr1, mgr2)
    if comp is None:
        return None
    # Determine if each version came from a system manager (for pkgrel stripping)
    p1 = _parse_version_for(comp, v1, is_system=(mgr1 in _SYSTEM_MANAGERS))
    p2 = _parse_version_for(comp, v2, is_system=(mgr2 in _SYSTEM_MANAGERS))
    if p1 is not None and p2 is not None and type(p1) is type(p2):
        return p1 > p2
    return None


def _best_version(versions: dict[str, str]) -> tuple[str | None, str | None]:
    """Pick the highest version from a {manager: version} mapping.

    Only managers that hold a comparable version participate. Returns
    (None, None) when nothing is comparable, or when no manager is *strictly*
    higher than another (equal versions are not a finding).
    """
    best_mgr = None
    best_ver = None
    has_comparable = False
    for mgr, ver in versions.items():
        if best_ver is None:
            best_mgr, best_ver = mgr, ver
            continue
        cmp = _version_greater(mgr, ver, best_mgr, best_ver)
        if cmp is True:
            best_mgr, best_ver = mgr, ver
            has_comparable = True
        elif cmp is False:
            has_comparable = True
    if not has_comparable:
        return None, None
    return best_mgr, best_ver


# ──────────────────────────────────────────────────────────────────────────────
# Core scan function
# ──────────────────────────────────────────────────────────────────────────────

async def cross_manager_newest(
    managers: list[PackageManager] | None = None,
    manager_filter: list[str] | None = None,
    include_ignored: bool = False,
    settings: Any | None = None,
) -> dict[str, Any]:
    """Scan installed packages across managers and find cross-manager version differences.

    Args:
        managers: Optional list of managers to scan. Defaults to all discovered.
        manager_filter: Optional list of manager names to restrict scan to.
        include_ignored: If False, filter out suggestions where all versions are ignored.
        settings: Optional SettingsStore instance for alias map and scan policies.

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

    # Load settings
    if settings is None:
        settings = get_settings()
    scan_settings = settings.get_version_scan_settings()
    untrusted = _untrusted_pairs_from_settings(settings)

    # Gather installed versions per manager
    results: dict[str, dict[str, Any]] = {}
    awaitable_map = {m.name: m.list_installed_versions() for m in managers}

    for name, coro in awaitable_map.items():
        try:
            versions = await coro
            results[name] = {"ok": True, "versions": versions}
        except NotImplementedError:
            # Manager has no version data. Not a failure — but recorded explicitly so
            # a caller can tell "this manager doesn't participate" from "this manager
            # was queried and has nothing".
            results[name] = {"ok": True, "unsupported": True, "versions": {}}
        except DriverError as e:
            # A real query failure (dead subprocess, nonzero exit). Surfaced, not
            # folded into an empty version map, so the scan reports which managers
            # it could not actually read.
            results[name] = {"ok": False, "error": describe_error(e), "versions": {}}
        except Exception as e:
            results[name] = {"ok": False, "error": str(e), "versions": {}}

    # Build alias resolution map from settings
    alias_map = settings.get_alias_map()

    def resolve_alias(manager: str, actual_name: str) -> str:
        """Resolve an actual package name to its normalized form using alias map."""
        for norm_name, managers in alias_map.items():
            if managers.get(manager) == actual_name:
                return norm_name
        return _normalize_name(actual_name)

    # Group by normalized name across managers (with alias resolution).
    # Versions that are not real release numbers (RubyGems' `default:` stdlib gems,
    # driver placeholders) are dropped here rather than carried into the grouping, so
    # they can never win a comparison.
    groups: dict[str, dict[str, str]] = {}  # norm_name -> {manager: version}
    for mgr_name, res in results.items():
        if not res.get("ok"):
            continue
        for pkg_name, version in res.get("versions", {}).items():
            if not _is_comparable_version(version):
                continue
            norm = resolve_alias(mgr_name, pkg_name)
            groups.setdefault(norm, {})[mgr_name] = version

    # Build suggestions: packages present on ≥2 *comparable* managers, where one
    # manager holds a strictly higher version.
    suggestions = []
    for norm_name, versions_by_mgr in groups.items():
        if len(versions_by_mgr) < 2:
            continue

        # Restrict to managers that can be legitimately compared with at least one
        # other. A group can hold managers from incompatible ecosystems (a Ruby gem
        # and a PyPI package of the same name), or a pair whose two version schemes
        # are independent (RubyGems vs a distro, same-registry JS). Both are dropped
        # so only like-for-like comparisons remain.
        comparable_mgrs = [
            m for m in versions_by_mgr
            if any(_pair_comparable(m, o, untrusted) for o in versions_by_mgr if o != m)
        ]
        if len(comparable_mgrs) < 2:
            continue
        comparable = {m: versions_by_mgr[m] for m in comparable_mgrs}

        best_mgr, best_ver = _best_version(comparable)
        if best_mgr is None:
            continue

        # Confirm the best is actually higher than at least one comparable peer.
        higher_elsewhere = any(
            m != best_mgr
            and _pair_comparable(best_mgr, m, untrusted)
            and _version_greater(best_mgr, best_ver, m, comparable[m]) is True
            for m in comparable
        )
        if not higher_elsewhere:
            continue

        # A distro manager and a runtime manager number the same release
        # independently, so their versions are not reliably orderable. Report these
        # only when the setting allows it, and always flag them when reported.
        cross_ecosystem = any(
            (m in _DISTRO_MANAGERS) != (best_mgr in _DISTRO_MANAGERS)
            for m in comparable
        )
        if cross_ecosystem and not scan_settings.get("include_cross_ecosystem", True):
            continue

        installed_actual = dict(versions_by_mgr)

        note = "alias-matched" if norm_name in alias_map else None
        if note is None and _RUNTIME_ECOSYSTEMS.get(best_mgr) == "js":
            if any(_RUNTIME_ECOSYSTEMS.get(m) == "js" for m in comparable if m != best_mgr):
                note = "same-registry"

        # Distro-vs-runtime comparisons span two independent version schemes and are
        # not reliably orderable. Protobuf is the live example: Arch ships 36.1-1.1
        # while the Ruby gem is 4.36.1, so a numeric comparison reports a "newer"
        # version that is simply the same release counted differently. These are
        # reported but explicitly marked, and can be turned off in settings.
        if note is None and cross_ecosystem:
            note = "cross-ecosystem-unverified"

        suggestions.append({
            "package": norm_name,
            "installed": installed_actual,
            "newest": {"manager": best_mgr, "version": best_ver},
            "note": note,
        })

    # Filter ignored suggestions (per-manager)
    if not include_ignored and not scan_settings.get("include_ignored", False):
        store = IgnoreStore()
        filtered = []
        for s in suggestions:
            # A suggestion is ignored if ALL its installed versions are ignored per-manager
            ignored = all(
                store.is_ignored(mgr, s["package"]) for mgr in s["installed"]
            )
            if not ignored:
                filtered.append(s)
        suggestions = filtered

    return {
        "suggestions": suggestions,
        "managers": {name: res for name, res in results.items()},
    }


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

    result = await cross_manager_newest(
        managers=managers,
        manager_filter=manager_filter,
        include_ignored=include_ignored,
    )

    # Exit code: 0 if ≥1 manager succeeded, 2 if zero succeeded
    any_ok = any(res.get("ok") for res in result["managers"].values())
    exit_code = 0 if any_ok else 2
    return exit_code, result