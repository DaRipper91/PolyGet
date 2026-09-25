import json
import sys

import pytest

import app.cli as cli
import app.core.history_store as history_store
import app.core.ignore_store as ignore_store
from app.core.manager import PackageManager


class FakeManager(PackageManager):
    name = "Fake"
    category = "Language/Dev"

    def __init__(self, updates=None, fail=False, sync_cmd=None):
        self._updates = updates or []
        self._fail = fail
        self._sync_cmd = sync_cmd

    def is_available(self):
        return True

    async def check_updates(self):
        if self._fail:
            raise RuntimeError("registry unreachable")
        return list(self._updates)

    def get_upgrade_command(self, packages=None):
        return ["fake", "upgrade"] + list(packages or [])

    def get_install_command(self, package):
        return ["fake", "install", package]

    def get_sync_command(self):
        return self._sync_cmd


class OtherManager(FakeManager):
    name = "Other"


@pytest.fixture
def managers(monkeypatch, tmp_path):
    """Swap driver discovery for fakes and point both stores at a temp dir."""
    fake = FakeManager(updates=[
        {"name": "alpha", "current": "1.0", "new": "2.0"},
        {"name": "beta", "current": "1.0", "new": "1.1"},
    ])
    other = OtherManager(fail=True)
    pool = [fake, other]
    monkeypatch.setattr(cli, "discover_managers", lambda: pool)
    monkeypatch.setattr(cli, "get_all_managers", lambda: pool)

    ignore_path = tmp_path / "ignored.json"
    history_path = tmp_path / "history.jsonl"
    orig_ignore_init = ignore_store.IgnoreStore.__init__
    monkeypatch.setattr(
        ignore_store.IgnoreStore, "__init__",
        lambda self, path=ignore_path: orig_ignore_init(self, path),
    )
    orig_record = history_store.record_upgrade
    monkeypatch.setattr(
        history_store, "record_upgrade",
        lambda m, p, s, path=history_path: orig_record(m, p, s, path),
    )
    return {"fake": fake, "other": other, "history": history_path, "ignore": ignore_path}


def run_json(capsys, *argv):
    code = cli.main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_outdated_reports_updates_and_per_manager_errors(managers, capsys):
    code, data = run_json(capsys, "outdated")
    assert code == cli.EXIT_FAILED
    assert [u["name"] for u in data["updates"]] == ["alpha", "beta"]
    assert data["managers"]["Fake"] == {"ok": True, "count": 2}
    assert data["managers"]["Other"]["ok"] is False
    assert "registry unreachable" in data["managers"]["Other"]["error"]


def test_json_flag_accepted_after_subcommand(managers, capsys):
    code = cli.main(["outdated", "-m", "fake", "--json"])
    assert code == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["managers"] == {"Fake": {"ok": True, "count": 2}}


def test_unknown_manager_is_usage_error(managers, capsys):
    code = cli.main(["--json", "outdated", "-m", "nope"])
    assert code == cli.EXIT_USAGE
    assert "unknown" in json.loads(capsys.readouterr().out)["error"]


def test_upgrade_without_yes_only_plans(managers, capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: ran.append(a))
    code, data = run_json(capsys, "upgrade", "-m", "fake")
    assert code == cli.EXIT_OK
    assert ran == []
    assert data["executed"] is False
    assert data["steps"][0]["command"] == ["fake", "upgrade", "alpha", "beta"]


def test_upgrade_skips_ignored_packages(managers, capsys):
    cli.main(["ignore", "add", "fake", "beta"])
    capsys.readouterr()
    _, data = run_json(capsys, "upgrade", "-m", "fake")
    assert data["steps"][0]["packages"] == ["alpha"]


def test_upgrade_with_yes_executes_and_records_history(managers, capsys, monkeypatch):
    class Done:
        returncode = 0

    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **k: calls.append(cmd) or Done())
    code, data = run_json(capsys, "upgrade", "-m", "fake", "alpha", "--yes")
    assert code == cli.EXIT_OK
    assert calls == [["fake", "upgrade", "alpha"]]
    assert data["steps"][0]["success"] is True
    entry = json.loads(managers["history"].read_text().splitlines()[0])
    assert entry["manager"] == "Fake" and entry["packages"] == ["alpha"] and entry["success"]


def test_failed_command_returns_failure(managers, capsys, monkeypatch):
    class Failed:
        returncode = 3

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **k: Failed())
    code, data = run_json(capsys, "install", "-m", "fake", "pkg", "-y")
    assert code == cli.EXIT_FAILED
    assert data["steps"][0]["returncode"] == 3


def test_upgrade_packages_require_single_manager(managers, capsys):
    assert cli.main(["upgrade", "alpha"]) == cli.EXIT_USAGE


def test_sync_skips_managers_without_sync_command(managers, capsys):
    managers["fake"]._sync_cmd = ["fake", "refresh"]
    _, data = run_json(capsys, "sync")
    assert data["steps"] == [{"manager": "Fake", "command": ["fake", "refresh"]}]


def test_main_routes_subcommands_to_cli(monkeypatch):
    import app.main

    seen = {}
    monkeypatch.setattr(sys, "argv", ["run.py", "managers", "--json"])
    monkeypatch.setattr(cli, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    app.main.main()
    assert seen["argv"] == ["managers", "--json"]
