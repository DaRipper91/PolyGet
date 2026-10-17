import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.drivers.bundler import BundlerManager
from app.core.drivers.gradle import GradleManager
from app.core.manager import DriverError
from app.core.projects import make_target, resolve_single_project, split_target
from app.core.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path):
    s = SettingsStore(path=tmp_path / "settings.json")
    with patch("app.core.projects.get_settings", return_value=s):
        yield s


def _ruby_project(root: Path, name: str) -> Path:
    p = root / name
    p.mkdir()
    (p / "Gemfile").write_text("source 'https://rubygems.org'\n")
    return p


def _gradle_project(root: Path, name: str, version: str) -> Path:
    p = root / name
    (p / "gradle" / "wrapper").mkdir(parents=True)
    (p / "gradlew").write_text("#!/bin/sh\n")
    (p / "gradle" / "wrapper" / "gradle-wrapper.properties").write_text(
        f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{version}-bin.zip\n"
    )
    return p


def test_settings_project_dirs_roundtrip(tmp_path):
    s = SettingsStore(path=tmp_path / "s.json")
    assert s.get_project_dirs() == []
    assert s.add_project_dir("/a") and not s.add_project_dir("/a")
    assert SettingsStore(path=tmp_path / "s.json").get_project_dirs() == ["/a"]
    assert s.remove_project_dir("/a") and not s.remove_project_dir("/a")


def test_settings_migration_adds_projects_to_old_files(tmp_path):
    old = tmp_path / "old.json"
    old.write_text('{"schema_version": 0, "alias_map": {}}')
    assert SettingsStore(path=old).get_project_dirs() == []


def test_target_encoding_roundtrip_and_rejects_plain_names():
    assert split_target(make_target("rake", Path("/p/app"))) == ("rake", Path("/p/app"))
    with pytest.raises(DriverError):
        split_target("rake")


def test_unconfigured_drivers_are_hidden_not_clean(store):
    with patch("app.core.drivers.bundler.shutil.which", return_value="/usr/bin/bundle"), \
         patch("app.core.drivers.gradle.shutil.which", return_value="/usr/bin/gradle"):
        assert not BundlerManager().is_available()
        assert not GradleManager().is_available()


def test_bundler_available_only_with_a_tracked_gemfile(store, tmp_path):
    store.add_project_dir(str(_ruby_project(tmp_path, "app")))
    with patch("app.core.drivers.bundler.shutil.which", return_value="/usr/bin/bundle"):
        assert BundlerManager().is_available()


def test_bundler_check_updates_parses_real_output_format(store, tmp_path, scripted_exec):
    app = _ruby_project(tmp_path, "app")
    store.add_project_dir(str(app))
    scripted_exec.add("bundle outdated", rc=1, stdout=(
        "Fetching gem metadata from https://rubygems.org/.\nResolving dependencies...\n\n"
        "rake (newest 13.4.2, installed 12.3.3, requested ~> 12.3.0)\n"
    ))
    assert asyncio.run(BundlerManager().check_updates()) == [
        {"name": f"rake @ {app}", "current": "12.3.3", "new": "13.4.2"}
    ]
    assert scripted_exec.calls[0][1]["cwd"] == app


def test_bundler_check_updates_all_projects_failing_raises(store, tmp_path, scripted_exec):
    store.add_project_dir(str(_ruby_project(tmp_path, "app")))
    scripted_exec.add("bundle outdated", rc=2, stderr="Could not find gem")
    with pytest.raises(DriverError):
        asyncio.run(BundlerManager().check_updates())


def test_bundler_installed_versions_from_bundle_list(store, tmp_path, scripted_exec):
    store.add_project_dir(str(_ruby_project(tmp_path, "app")))
    scripted_exec.add("bundle list", stdout="Gems included by the bundle:\n  * rake (12.3.3)\n  * rack (3.0.0)\nUse `bundle info`\n")
    assert asyncio.run(BundlerManager().list_installed_versions()) == {"rake": "12.3.3", "rack": "3.0.0"}


def test_bundler_upgrade_command_targets_project_via_env(store, tmp_path):
    app = _ruby_project(tmp_path, "app")
    store.add_project_dir(str(app))
    mgr = BundlerManager()
    assert mgr.get_upgrade_command([f"rake @ {app}"]) == ["env", f"BUNDLE_GEMFILE={app}/Gemfile", "bundle", "update", "rake"]
    assert mgr.get_upgrade_command() == ["env", f"BUNDLE_GEMFILE={app}/Gemfile", "bundle", "update"]


def test_upgrade_refuses_ambiguous_multi_project_selection(store, tmp_path):
    a, b = _ruby_project(tmp_path, "a"), _ruby_project(tmp_path, "b")
    store.add_project_dir(str(a)); store.add_project_dir(str(b))
    with pytest.raises(DriverError, match="one project at a time"):
        BundlerManager().get_upgrade_command([f"rake @ {a}", f"rake @ {b}"])
    with pytest.raises(DriverError, match="one project at a time"):
        resolve_single_project(None, "Gemfile", "Bundler")


def test_gradle_reports_wrapper_versions_against_latest(store, tmp_path, scripted_exec):
    old = _gradle_project(tmp_path, "old", "8.5")
    new = _gradle_project(tmp_path, "new", "9.8.1")
    store.add_project_dir(str(old)); store.add_project_dir(str(new))
    scripted_exec.add("services.gradle.org/versions/current", stdout='{"version": "9.8.1"}')
    assert asyncio.run(GradleManager().check_updates()) == [
        {"name": f"gradle wrapper @ {old}", "current": "8.5", "new": "9.8.1"}
    ]


def test_gradle_ignores_projects_without_a_wrapper(store, tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    store.add_project_dir(str(bare))
    with patch("app.core.drivers.gradle.shutil.which", return_value="/usr/bin/gradle"):
        assert not GradleManager().is_available()


def test_gradle_upgrade_uses_the_wrapper_with_latest_label(store, tmp_path):
    proj = _gradle_project(tmp_path, "p", "8.5")
    store.add_project_dir(str(proj))
    assert GradleManager().get_upgrade_command() == [
        f"{proj}/gradlew", "-p", str(proj), "wrapper", "--gradle-version", "latest"
    ]
