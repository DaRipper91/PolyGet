import json

import pytest

import app.cli as cli
import app.core.settings_store as settings_store
from app.core.manager import DriverError, PackageManager
from app.core.distro import get_distro_family


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = settings_store.SettingsStore(path=tmp_path / "settings.json")
    monkeypatch.setattr(settings_store, "_settings_instance", s)
    return s


def run_json(capsys, *argv):
    code = cli.main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_projects_add_list_remove(store, tmp_path, capsys):
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "Gemfile").write_text("")
    code, rows = run_json(capsys, "projects", "add", str(proj))
    assert code == cli.EXIT_OK
    assert rows == [{"directory": str(proj), "bundler": True, "gradle": False}]
    assert store.get_project_dirs() == [str(proj)]
    _, rows = run_json(capsys, "projects", "remove", str(proj))
    assert rows == [] and store.get_project_dirs() == []


def test_projects_add_rejects_missing_directory(store, tmp_path, capsys):
    code = cli.main(["--json", "projects", "add", str(tmp_path / "nope")])
    assert code == cli.EXIT_USAGE
    assert "not a directory" in json.loads(capsys.readouterr().out)["error"]
    assert store.get_project_dirs() == []


def test_projects_add_requires_directory(store, capsys):
    assert cli.main(["--json", "projects", "add"]) == cli.EXIT_USAGE


class Unbuildable(PackageManager):
    name = "Unbuildable"
    category = "Language/Dev"

    def is_available(self):
        return True

    def get_upgrade_command(self, packages=None):
        raise DriverError("select packages from a single project")


@pytest.mark.parametrize("exc", [DriverError("ambiguous"), NotImplementedError("no upgrade path")])
def test_upgrade_reports_unbuildable_command_instead_of_crashing(monkeypatch, capsys, exc):
    mgr = Unbuildable()
    mgr.get_upgrade_command = lambda packages=None: (_ for _ in ()).throw(exc)
    monkeypatch.setattr(cli, "discover_managers", lambda: [mgr])
    monkeypatch.setattr(cli, "get_all_managers", lambda: [mgr])
    code, data = run_json(capsys, "upgrade", "-m", "unbuildable", "pkg")
    assert code == cli.EXIT_FAILED
    assert data == {"executed": False, "steps": []}


def test_macos_is_detected_as_its_own_family(monkeypatch):
    get_distro_family.cache_clear()
    monkeypatch.setattr("app.core.distro.sys.platform", "darwin")
    try:
        assert get_distro_family() == "macos"
    finally:
        get_distro_family.cache_clear()


class NoUpdateQuery(PackageManager):
    name = "NoQuery"
    category = "Universal"

    def is_available(self):
        return True

    async def check_updates(self):
        raise NotImplementedError("cannot report outdated packages")


class Broken(NoUpdateQuery):
    name = "Broken"

    async def check_updates(self):
        raise RuntimeError("registry unreachable")


def _use(monkeypatch, *mgrs):
    monkeypatch.setattr(cli, "discover_managers", lambda: list(mgrs))
    monkeypatch.setattr(cli, "get_all_managers", lambda: list(mgrs))


def test_outdated_unsupported_manager_is_flagged_but_not_a_failure(monkeypatch, capsys):
    _use(monkeypatch, NoUpdateQuery())
    code, data = run_json(capsys, "outdated")
    assert code == cli.EXIT_OK
    assert data["managers"]["NoQuery"] == {
        "ok": False, "error": "cannot report outdated packages", "unsupported": True,
    }


def test_outdated_real_failure_still_fails_next_to_an_unsupported_manager(monkeypatch, capsys):
    _use(monkeypatch, NoUpdateQuery(), Broken())
    code, data = run_json(capsys, "outdated")
    assert code == cli.EXIT_FAILED
    assert "unsupported" not in data["managers"]["Broken"]
