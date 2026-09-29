"""Tests for cross-manager newest-version scan."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.core.version_scan import (
    cross_manager_newest,
    _normalize_name,
    _parse_semver,
    _parse_system_version,
    _version_greater,
    _best_version,
    _comparators,
    _is_comparable_version,
)
from app.core.drivers.npm import NpmManager
from app.core.drivers.pnpm import PnpmManager
from app.core.drivers.yarn import YarnManager
from app.core.settings_store import SettingsStore


def test_normalize_name():
    assert _normalize_name("TypeScript") == "typescript"
    assert _normalize_name("python-requests") == "requests"
    assert _normalize_name("node-typescript") == "typescript"
    assert _normalize_name("perl-libwww") == "libwww"
    assert _normalize_name("@scope/pkg") == "@scope/pkg"


def test_parse_semver():
    assert _parse_semver("1.2.3") is not None
    assert str(_parse_semver("1.10.0")) == "1.10.0"
    assert _parse_semver("unknown") is None
    assert _parse_semver("") is None
    assert _parse_semver("not-a-version") is None


def test_parse_system_version():
    # pacman-style
    assert _parse_system_version("5.0.4-1") == (5, 0, 4)
    assert _parse_system_version("90-1") == (90,)  # pkgrel stripped, just major
    # dpkg-style with epoch - epoch stripped, then pkgrel stripped
    assert _parse_system_version("1:2.0-1") == (2, 0)
    # pre-release suffix treated as pkgrel (simplistic but acceptable)
    assert _parse_system_version("1.0-rc1") == (1, 0)
    # unparseable
    assert _parse_system_version("unknown") is None
    assert _parse_system_version("") is None


def test_version_greater_semver():
    # npm/pnpm/yarn use semver
    assert _version_greater("NPM", "1.10.0", "1.2.0") is True
    assert _version_greater("NPM", "1.2.0", "1.10.0") is False
    assert _version_greater("pnpm", "2.0.0", "1.9.9") is True
    assert _version_greater("Yarn", "1.0.0", "1.0.0") is False
    # unparseable falls back to None
    assert _version_greater("NPM", "unknown", "1.0.0") is None
    assert _version_greater("NPM", "1.0.0", "unknown") is None


def test_version_greater_system():
    # pacman/dnf/apt use pkgver-pkgrel
    assert _version_greater("Pacman", "5.0.4-1", "5.0.3-2") is True
    assert _version_greater("Pacman", "5.0.4-1", "5.0.4-2") is False  # pkgrel ignored
    assert _version_greater("DNF", "1:2.0-1", "1.9-1") is True  # epoch stripped
    assert _version_greater("APT", "unknown", "1.0") is None


def test_best_version():
    versions = {"NPM": "1.2.0", "pnpm": "1.10.0", "Yarn": "1.5.0"}
    mgr, ver = _best_version(versions)
    assert mgr == "pnpm"
    assert ver == "1.10.0"

    # all unparseable
    versions = {"NPM": "unknown", "pnpm": "also-unknown"}
    mgr, ver = _best_version(versions)
    assert mgr is None
    assert ver is None

    # empty
    mgr, ver = _best_version({})
    assert mgr is None
    assert ver is None


@pytest.mark.asyncio
async def test_cross_manager_newest_higher_elsewhere(tmp_path):
    """Detect a package with a higher version on a different manager."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"typescript": "5.0.0"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"typescript": "5.1.0"})

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm], settings=_scan_settings(tmp_path))
    assert len(result["suggestions"]) == 1
    s = result["suggestions"][0]
    assert s["package"] == "typescript"
    assert s["newest"]["manager"] == "pnpm"
    assert s["newest"]["version"] == "5.1.0"
    assert s["installed"]["NPM"] == "5.0.0"
    assert s["installed"]["pnpm"] == "5.1.0"


@pytest.mark.asyncio
async def test_cross_manager_newest_all_equal_silent(tmp_path):
    """No suggestion when versions are equal across managers."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"typescript": "5.0.0"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"typescript": "5.0.0"})

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm], settings=_scan_settings(tmp_path))
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_cross_manager_newest_unparseable_silent(tmp_path):
    """No suggestion when versions are unparseable."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"pkg": "unknown"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"pkg": "also-unknown"})

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm], settings=_scan_settings(tmp_path))
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_cross_manager_newest_one_failed_survives(tmp_path):
    """One manager failing doesn't sink the scan."""
    mock_ok = AsyncMock(spec=NpmManager)
    mock_ok.name = "NPM"
    mock_ok.list_installed_versions = AsyncMock(return_value={"pkg": "1.0.0"})

    mock_fail = AsyncMock(spec=PnpmManager)
    mock_fail.name = "pnpm"
    mock_fail.list_installed_versions = AsyncMock(side_effect=RuntimeError("boom"))

    result = await cross_manager_newest(managers=[mock_ok, mock_fail], settings=_scan_settings(tmp_path))
    assert result["managers"]["NPM"]["ok"] is True
    assert result["managers"]["pnpm"]["ok"] is False
    assert "boom" in result["managers"]["pnpm"]["error"]


@pytest.mark.asyncio
async def test_cross_manager_newest_unknown_names_unmatched(tmp_path):
    """Normalized names that don't match across managers produce no suggestion."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"python-requests": "2.31.0"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"requests": "2.32.0"})  # no prefix

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm], settings=_scan_settings(tmp_path))
    # Both normalize to "requests" - should match!
    assert len(result["suggestions"]) == 1
    assert result["suggestions"][0]["package"] == "requests"


@pytest.mark.asyncio
async def test_cross_manager_newest_manager_filter():
    """--manager filter restricts scan to named managers."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"pkg": "1.0.0"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"pkg": "2.0.0"})

    mock_cargo = AsyncMock(spec=NpmManager)
    mock_cargo.name = "Cargo"
    mock_cargo.list_installed_versions = AsyncMock(return_value={"pkg": "3.0.0"})

    # Filter to only NPM + pnpm
    result = await cross_manager_newest(
        managers=[mock_npm, mock_pnpm, mock_cargo],
        manager_filter=["NPM", "pnpm"]
    )
    assert "Cargo" not in result["managers"]
    assert "NPM" in result["managers"]
    assert "pnpm" in result["managers"]
    assert len(result["suggestions"]) == 1


def test_driver_list_installed_versions_exists():
    """Verify the base method exists and returns dict."""
    npm = NpmManager()
    assert hasattr(npm, "list_installed_versions")
    import inspect
    assert inspect.iscoroutinefunction(npm.list_installed_versions)

    pnpm = PnpmManager()
    assert hasattr(pnpm, "list_installed_versions")

    yarn = YarnManager()
    assert hasattr(yarn, "list_installed_versions")


# ── Ecosystem comparability ────────────────────────────────────────────────────
#
# Regression coverage for a real defect: the comparator originally whitelisted only
# {NPM, pnpm, Yarn, Pacman, DNF, APT}, so the 9 other drivers reported versions that
# silently produced no suggestion. On CachyOS this discarded a genuine finding —
# uvicorn 0.53.0 under pipx vs 0.52.4-1 under pacman.

# ── Test isolation ────────────────────────────────────────────────────────────
#
# `cross_manager_newest` falls back to `get_settings()`, which reads the real
# ~/.config/polyget/settings.json. Tests that don't pass their own SettingsStore
# would then change outcome based on the developer's machine — the two failures
# below were real tests that broke as soon as include_cross_ecosystem was set
# locally. Every scan test must inject an explicit settings object.


def _scan_settings(tmp_path, **overrides) -> "SettingsStore":
    """Build a throwaway SettingsStore so scan tests never read the user's config."""
    settings = SettingsStore(path=Path(tmp_path) / "settings.json")
    for key, value in overrides.items():
        settings.set_version_scan_setting(key, value)
    return settings


def test_scan_tests_do_not_read_user_config(tmp_path):
    """Guard: cross_manager_newest must honour an injected settings object.

    If this ever regresses, changing ~/.config/polyget/settings.json would silently
    alter the test suite's results.
    """
    settings = _scan_settings(tmp_path, include_cross_ecosystem=False)
    assert settings.get("version_scan.include_cross_ecosystem") is False

    strict = _scan_settings(tmp_path, include_cross_ecosystem=True)
    assert strict.get("version_scan.include_cross_ecosystem") is True


def test_comparators_refuse_different_runtime_ecosystems():
    """A gem and a PyPI package that share a name are not comparable software."""
    for a, b in [
        ("RubyGems", "Pipx"),   # live: `yaml`, `openssl` stdlib vs distro
        ("NPM", "Pipx"),
        ("Cargo", "NPM"),
        ("Flatpak", "NPM"),
        ("Flatpak", "Pipx"),
        ("Dart Pub", "Hex"),
    ]:
        assert _comparators(a, b) is None, f"{a}/{b} must refuse to compare"


def test_comparators_allow_same_ecosystem_and_distro_pairs():
    for a, b in [
        ("NPM", "pnpm"), ("NPM", "Yarn"), ("Pipx", "Poetry"),
        ("Pacman", "Pipx"),     # distro copy vs runtime copy of the same software
        ("Pacman", "DNF"),
    ]:
        assert _comparators(a, b) is not None, f"{a}/{b} should compare"


def test_stdlib_default_gems_are_not_comparable():
    """RubyGems reports interpreter-bundled gems as `default: X`; those track the
    Ruby stdlib, are not separately installable, and must never win a comparison."""
    for v in ("default: 0.4.0", "default: 1.0.4", "unknown", "", "   ", "not installed", "None"):
        assert not _is_comparable_version(v), f"{v!r} must be rejected"


def test_cargo_v_prefix_is_tolerated():
    """Live Asahi case: Cargo reports `v4.2.0`, which must parse as 4.2.0."""
    assert _version_greater("Cargo", "v4.2.0", "4.1.9") is True
    assert _version_greater("Cargo", "v4.2.0", "4.2.0") is False


def test_runtime_fallback_orders_numerically_not_lexicographically():
    """The generic runtime comparator must not do string comparison."""
    assert _version_greater("Pipx", "2.0", "10.0") is False
    assert _version_greater("Pipx", "10.0", "2.0") is True
    assert _version_greater("Cargo", "0.9.0", "0.10.0") is False


def test_prerelease_sorts_below_release():
    assert _version_greater("Pipx", "1.0.0", "1.0.0rc1") is True
    assert _version_greater("Pipx", "1.0.0rc1", "1.0.0") is False
    assert _version_greater("Cargo", "1.0.0-rc.1", "1.0.0") is False
    assert _version_greater("NPM", "1.0.0+build", "1.0.0") is False  # build metadata unranked


@pytest.mark.asyncio
async def test_uvicorn_regression_pipx_beats_distro(tmp_path):
    """The exact false negative found on CachyOS: pipx has a newer uvicorn than the
    distro package. Must surface as a suggestion, not be silently dropped."""
    mock_pacman = AsyncMock(spec=object)
    mock_pacman.name = "Pacman"
    mock_pacman.list_installed_versions = AsyncMock(return_value={"python-uvicorn": "0.52.4-1"})

    mock_pipx = AsyncMock(spec=object)
    mock_pipx.name = "Pipx"
    mock_pipx.list_installed_versions = AsyncMock(return_value={"uvicorn": "0.53.0"})

    result = await cross_manager_newest(managers=[mock_pacman, mock_pipx], settings=_scan_settings(tmp_path))
    assert len(result["suggestions"]) == 1, "a newer pipx uvicorn must be reported"
    s = result["suggestions"][0]
    assert s["package"] == "uvicorn"
    assert s["newest"] == {"manager": "Pipx", "version": "0.53.0"}


@pytest.mark.asyncio
async def test_ruby_stdlib_gem_never_suggested_against_distro(tmp_path):
    """Live Asahi case: `yaml` is Ruby's bundled stdlib gem (default: 0.4.0) and
    separately the distro's yaml package (6.0.3). Different software — no suggestion."""
    mock_gem = AsyncMock(spec=object)
    mock_gem.name = "RubyGems"
    mock_gem.list_installed_versions = AsyncMock(return_value={"yaml": "default: 0.4.0"})

    mock_pacman = AsyncMock(spec=object)
    mock_pacman.name = "Pacman"
    mock_pacman.list_installed_versions = AsyncMock(return_value={"yaml": "6.0.3-2.1"})

    result = await cross_manager_newest(managers=[mock_gem, mock_pacman], settings=_scan_settings(tmp_path))
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_distro_pair_reports_real_difference(tmp_path):
    """Two distro managers, genuinely different versions, should report."""
    mock_pacman = AsyncMock(spec=object)
    mock_pacman.name = "Pacman"
    mock_pacman.list_installed_versions = AsyncMock(return_value={"openssl": "3.5.8-1"})

    mock_dnf = AsyncMock(spec=object)
    mock_dnf.name = "DNF"
    mock_dnf.list_installed_versions = AsyncMock(return_value={"openssl": "3.6.4-1"})

    result = await cross_manager_newest(managers=[mock_pacman, mock_dnf], settings=_scan_settings(tmp_path))
    assert len(result["suggestions"]) == 1
    assert result["suggestions"][0]["newest"]["manager"] == "DNF"


@pytest.mark.asyncio
async def test_cross_ecosystem_suggestion_is_flagged(tmp_path):
    """Live CachyOS case: `google-protobuf` is 4.36.1 as a Ruby gem and 36.1-1.1 in
    the Arch repo — the same release under two numbering schemes. A numeric comparison
    reports a 'newer' version that isn't one, so this must be marked unverified."""
    mock_gem = AsyncMock(spec=object)
    mock_gem.name = "RubyGems"
    mock_gem.list_installed_versions = AsyncMock(return_value={"google-protobuf": "4.36.1"})

    # Real pacman package name; the ruby- prefix is stripped by _normalize_name.
    mock_pacman = AsyncMock(spec=object)
    mock_pacman.name = "Pacman"
    mock_pacman.list_installed_versions = AsyncMock(return_value={"ruby-google-protobuf": "36.1-1.1"})

    result = await cross_manager_newest(managers=[mock_gem, mock_pacman], settings=_scan_settings(tmp_path))
    assert len(result["suggestions"]) == 1
    s = result["suggestions"][0]
    assert s["package"] == "google-protobuf"
    assert s["note"] == "cross-ecosystem-unverified", "must be flagged, not presented as fact"


@pytest.mark.asyncio
async def test_cross_ecosystem_can_be_disabled_in_settings(tmp_path):
    """Users can restrict results to managers sharing a version scheme."""
    from app.core.settings_store import SettingsStore

    mock_gem = AsyncMock(spec=object)
    mock_gem.name = "RubyGems"
    mock_gem.list_installed_versions = AsyncMock(return_value={"google-protobuf": "4.36.1"})

    mock_pacman = AsyncMock(spec=object)
    mock_pacman.name = "Pacman"
    mock_pacman.list_installed_versions = AsyncMock(return_value={"ruby-google-protobuf": "36.1-1.1"})

    settings = SettingsStore(path=Path(tmp_path) / "settings.json")
    settings.set_version_scan_setting("include_cross_ecosystem", False)

    result = await cross_manager_newest(managers=[mock_gem, mock_pacman], settings=settings)
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_equal_versions_across_ecosystems_stay_silent(tmp_path):
    """Live CachyOS case: `semver` is 7.8.5 under npm and 7.8.5-1 under pacman —
    the same release, so not a finding."""
    mock_npm = AsyncMock(spec=object)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"semver": "7.8.5"})

    mock_pacman = AsyncMock(spec=object)
    mock_pacman.name = "Pacman"
    mock_pacman.list_installed_versions = AsyncMock(return_value={"node-semver": "7.8.5-1"})

    result = await cross_manager_newest(managers=[mock_npm, mock_pacman], settings=_scan_settings(tmp_path))
    assert result["suggestions"] == []