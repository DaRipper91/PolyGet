import asyncio
import json
from unittest.mock import patch

import pytest

from app.core.drivers import brew as brew_mod
from app.core.drivers.brew import HomebrewManager
from app.core.drivers.conda import CondaManager
from app.core.manager import DriverError


@pytest.fixture
def brew_on_path():
    with patch.object(brew_mod.shutil, "which", return_value="/usr/local/bin/brew"):
        yield


def test_brew_found_via_standard_prefix_when_not_on_path(tmp_path):
    linuxbrew = tmp_path / "brew"
    linuxbrew.write_text("")
    with patch.object(brew_mod.shutil, "which", return_value=None), \
         patch.object(brew_mod, "_PREFIX_CANDIDATES", ("/nonexistent/brew", str(linuxbrew))):
        assert HomebrewManager().is_available()
        assert HomebrewManager().get_install_command("jq")[0] == str(linuxbrew)
    with patch.object(brew_mod.shutil, "which", return_value=None), \
         patch.object(brew_mod, "_PREFIX_CANDIDATES", ("/nonexistent/brew",)):
        assert not HomebrewManager().is_available()


def test_brew_check_updates_merges_formulae_and_casks(brew_on_path, scripted_exec):
    scripted_exec.add("outdated --json=v2", stdout=json.dumps({
        "formulae": [{"name": "jq", "installed_versions": ["1.6", "1.7"], "current_version": "1.7.1"}],
        "casks": [{"name": "firefox", "installed_versions": "128.0", "current_version": "129.0"}],
    }))
    assert asyncio.run(HomebrewManager().check_updates()) == [
        {"name": "jq", "current": "1.7", "new": "1.7.1"},
        {"name": "firefox", "current": "128.0", "new": "129.0"},
    ]


def test_brew_bad_json_is_driver_error(brew_on_path, scripted_exec):
    scripted_exec.add("outdated", stdout="Error: something")
    with pytest.raises(DriverError):
        asyncio.run(HomebrewManager().check_updates())


@pytest.mark.parametrize("platform,expected_calls", [("linux", 1), ("darwin", 2)])
def test_brew_casks_are_only_queried_on_macos(brew_on_path, scripted_exec, platform, expected_calls):
    scripted_exec.add("list --formula --versions", stdout="jq 1.6 1.7\nwget 1.21\n")
    scripted_exec.add("list --cask --versions", stdout="firefox 129.0\n")
    with patch.object(brew_mod.sys, "platform", platform):
        versions = asyncio.run(HomebrewManager().list_installed_versions())
    assert len(scripted_exec.calls) == expected_calls
    assert versions["jq"] == "1.7" and versions["wget"] == "1.21"
    assert ("firefox" in versions) == (platform == "darwin")


def test_brew_search_skips_headings_and_no_match_is_empty(brew_on_path, scripted_exec):
    scripted_exec.add("search jq", stdout="==> Formulae\njq\njqp\n\n==> Casks\njq-app\n")
    assert [r["name"] for r in asyncio.run(HomebrewManager().search_packages("jq"))] == ["jq", "jqp", "jq-app"]
    scripted_exec.rules.clear()
    scripted_exec.add("search zzz", rc=1, stderr="Error: No formulae or casks found for zzz.")
    assert asyncio.run(HomebrewManager().search_packages("zzz")) == []


def test_brew_taps_map_to_github_repos(brew_on_path, scripted_exec):
    scripted_exec.add("brew tap", stdout="homebrew/core\nuser/tools\n")
    repos = asyncio.run(HomebrewManager().list_repos())
    assert repos[1] == {"id": "user/tools", "name": "user/tools", "url": "https://github.com/user/homebrew-tools", "enabled": True}
    mgr = HomebrewManager()
    assert mgr.get_add_repo_command("user/tools")[1:] == ["tap", "user/tools"]
    assert mgr.get_remove_repo_command("user/tools")[1:] == ["untap", "user/tools"]
    assert mgr.supports_repos


def test_brew_commands(brew_on_path):
    mgr = HomebrewManager()
    assert mgr.get_upgrade_command(["jq"]) == ["/usr/local/bin/brew", "upgrade", "jq"]
    assert mgr.get_sync_command() == ["/usr/local/bin/brew", "update"]


DRY_RUN = {"success": True, "actions": {
    "UNLINK": [{"name": "numpy", "version": "1.26.0"}, {"name": "openssl", "version": "3.0.1"}],
    "LINK": [{"name": "numpy", "version": "2.0.1"}, {"name": "openssl", "version": "3.0.1"},
             {"name": "brand-new-dep", "version": "1.0"}],
}}


@pytest.fixture
def conda_on_path():
    with patch("app.core.drivers.conda.shutil.which", side_effect=lambda b: f"/bin/{b}" if b == "conda" else None):
        yield


def test_conda_updates_pair_unlink_with_link_and_ignore_new_deps(conda_on_path, scripted_exec):
    scripted_exec.add("update --all --dry-run --json", stdout=json.dumps(DRY_RUN))
    assert asyncio.run(CondaManager().check_updates()) == [{"name": "numpy", "current": "1.26.0", "new": "2.0.1"}]


def test_conda_nothing_to_update_is_empty(conda_on_path, scripted_exec):
    scripted_exec.add("--dry-run", stdout=json.dumps({"success": True, "message": "All requested packages already installed."}))
    assert asyncio.run(CondaManager().check_updates()) == []


def test_conda_installed_and_search(conda_on_path, scripted_exec):
    scripted_exec.add("conda list --json", stdout=json.dumps([{"name": "numpy", "version": "1.26.0"}]))
    scripted_exec.add("conda search *pandas* --json", stdout=json.dumps({
        "pandas": [{"version": "2.1.0"}, {"version": "2.2.0"}], "pandas-stubs": [{"version": "2.2.1"}],
    }))
    mgr = CondaManager()
    assert asyncio.run(mgr.list_installed_versions()) == {"numpy": "1.26.0"}
    results = asyncio.run(mgr.search_packages("pandas"))
    assert {r["name"]: r["version"] for r in results} == {"pandas": "2.2.0", "pandas-stubs": "2.2.1"}


def test_conda_search_distinguishes_no_match_from_failure(conda_on_path, scripted_exec):
    scripted_exec.add("search", rc=1, stdout=json.dumps({"error": "x", "exception_name": "PackagesNotFoundError"}))
    assert asyncio.run(CondaManager().search_packages("zzz")) == []
    scripted_exec.rules.clear()
    scripted_exec.add("search", rc=1, stdout=json.dumps({"error": "channel unreachable", "exception_name": "HTTPError"}))
    with pytest.raises(DriverError, match="channel unreachable"):
        asyncio.run(CondaManager().search_packages("x"))


def test_conda_commands(conda_on_path):
    mgr = CondaManager()
    assert mgr.get_upgrade_command() == ["conda", "update", "-y", "--all"]
    assert mgr.get_upgrade_command(["numpy"]) == ["conda", "update", "-y", "numpy"]
    assert mgr.get_install_command("numpy") == ["conda", "install", "-y", "numpy"]
