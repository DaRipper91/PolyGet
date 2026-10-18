"""Pre/post hooks around upgrades and removals."""

import json

import pytest

import app.cli as cli
import app.core.history_store as history_store
import app.core.settings_store as settings_store
from app.core import hooks
from app.core.manager import PackageManager


class Fake(PackageManager):
    name = "Fake"

    def is_available(self):
        return True

    async def check_updates(self):
        return [{"name": "alpha", "current": "1", "new": "2"}]

    async def still_outdated(self, packages):
        return []

    def get_upgrade_command(self, packages=None):
        return ["fake", "upgrade"] + list(packages or [])


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "_settings_instance", settings_store.SettingsStore(tmp_path / "s.json"))
    mgr = Fake()
    monkeypatch.setattr(cli, "discover_managers", lambda: [mgr])
    monkeypatch.setattr(cli, "get_all_managers", lambda: [mgr])
    monkeypatch.setattr(history_store, "record_upgrade", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_restart_hint", lambda: None)
    return tmp_path


def test_hook_filtering(env):
    hooks.add_hook("pre", ["snap", "shot"], managers=["Pacman"])
    hooks.add_hook("post", ["flatpak", "repair"], operations=["upgrade"])
    assert [h["command"] for h in hooks.hooks_for("pre", "upgrade", ["pacman", "Flatpak"])] == [["snap", "shot"]]
    assert hooks.hooks_for("pre", "upgrade", ["Flatpak"]) == []
    assert hooks.hooks_for("post", "remove", ["Flatpak"]) == []
    assert len(hooks.hooks_for("post", "upgrade", ["Flatpak"])) == 1


def test_bad_hooks_rejected(env):
    with pytest.raises(ValueError):
        hooks.add_hook("during", ["x"])
    with pytest.raises(ValueError):
        hooks.add_hook("pre", [])
    with pytest.raises(ValueError):
        hooks.add_hook("pre", ["x"], operations=["install"])


def test_plan_shows_hooks_around_steps(env, capsys):
    hooks.add_hook("pre", ["snap"])
    hooks.add_hook("post", ["tidy"])
    cli.main(["--json", "upgrade", "-m", "fake"])
    steps = json.loads(capsys.readouterr().out)["steps"]
    assert [s["command"] for s in steps] == [["snap"], ["fake", "upgrade", "alpha"], ["tidy"]]


def test_failed_pre_hook_stops_the_upgrade(env, capsys, monkeypatch):
    hooks.add_hook("pre", ["snap"])
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        return type("R", (), {"returncode": 1 if cmd == ["snap"] else 0})()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code = cli.main(["--json", "upgrade", "-m", "fake", "--yes"])
    steps = json.loads(capsys.readouterr().out)["steps"]
    assert code == cli.EXIT_FAILED and calls == [["snap"]]
    assert steps[1]["skipped"].startswith("pre-hook failed") and steps[1]["success"] is False


def test_post_hook_runs_after_and_failure_is_reported(env, capsys, monkeypatch):
    hooks.add_hook("post", ["tidy"])
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        return type("R", (), {"returncode": 1 if cmd == ["tidy"] else 0})()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code = cli.main(["--json", "upgrade", "-m", "fake", "--yes"])
    assert calls == [["fake", "upgrade", "alpha"], ["tidy"]] and code == cli.EXIT_FAILED


def test_hooks_cli_add_list_remove(env, capsys):
    assert cli.main(["hooks", "add", "pre", "-m", "pacman", "--", "pkexec", "snapper", "create", "-d", "polyget"]) == 0
    capsys.readouterr()
    cli.main(["--json", "hooks"])
    (hook,) = json.loads(capsys.readouterr().out)
    assert hook["command"] == ["pkexec", "snapper", "create", "-d", "polyget"] and hook["managers"] == ["pacman"]
    assert cli.main(["hooks", "remove", "1"]) == 0
    assert cli.main(["hooks", "remove", "1"]) == cli.EXIT_USAGE
    assert cli.main(["hooks", "add", "pre"]) == cli.EXIT_USAGE
