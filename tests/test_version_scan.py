"""Tests for cross-manager newest-version scan."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.version_scan import (
    cross_manager_newest,
    _normalize_name,
    _parse_semver,
    _parse_system_version,
    _version_greater,
    _best_version,
)
from app.core.drivers.npm import NpmManager
from app.core.drivers.pnpm import PnpmManager
from app.core.drivers.yarn import YarnManager


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
async def test_cross_manager_newest_higher_elsewhere():
    """Detect a package with a higher version on a different manager."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"typescript": "5.0.0"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"typescript": "5.1.0"})

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm])
    assert len(result["suggestions"]) == 1
    s = result["suggestions"][0]
    assert s["package"] == "typescript"
    assert s["newest"]["manager"] == "pnpm"
    assert s["newest"]["version"] == "5.1.0"
    assert s["installed"]["NPM"] == "5.0.0"
    assert s["installed"]["pnpm"] == "5.1.0"


@pytest.mark.asyncio
async def test_cross_manager_newest_all_equal_silent():
    """No suggestion when versions are equal across managers."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"typescript": "5.0.0"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"typescript": "5.0.0"})

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm])
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_cross_manager_newest_unparseable_silent():
    """No suggestion when versions are unparseable."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"pkg": "unknown"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"pkg": "also-unknown"})

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm])
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_cross_manager_newest_one_failed_survives():
    """One manager failing doesn't sink the scan."""
    mock_ok = AsyncMock(spec=NpmManager)
    mock_ok.name = "NPM"
    mock_ok.list_installed_versions = AsyncMock(return_value={"pkg": "1.0.0"})

    mock_fail = AsyncMock(spec=PnpmManager)
    mock_fail.name = "pnpm"
    mock_fail.list_installed_versions = AsyncMock(side_effect=RuntimeError("boom"))

    result = await cross_manager_newest(managers=[mock_ok, mock_fail])
    assert result["managers"]["NPM"]["ok"] is True
    assert result["managers"]["pnpm"]["ok"] is False
    assert "boom" in result["managers"]["pnpm"]["error"]


@pytest.mark.asyncio
async def test_cross_manager_newest_unknown_names_unmatched():
    """Normalized names that don't match across managers produce no suggestion."""
    mock_npm = AsyncMock(spec=NpmManager)
    mock_npm.name = "NPM"
    mock_npm.list_installed_versions = AsyncMock(return_value={"python-requests": "2.31.0"})

    mock_pnpm = AsyncMock(spec=PnpmManager)
    mock_pnpm.name = "pnpm"
    mock_pnpm.list_installed_versions = AsyncMock(return_value={"requests": "2.32.0"})  # no prefix

    result = await cross_manager_newest(managers=[mock_npm, mock_pnpm])
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