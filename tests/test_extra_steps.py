"""Drivers ported from comparable tools (fwupd, rustup, mise, fisher) and AUR PKGBUILD review."""

import asyncio
import json
import subprocess

import pytest

import app.cli as cli
import app.core.settings_store as settings_store
from app.core.drivers.aur import AurManager
from app.core.drivers.fisher import FisherManager
from app.core.drivers.fwupd import FwupdManager
from app.core.drivers.mise import MiseManager
from app.core.drivers.rustup import RustupManager, _parse_check
from app.core.manager import DriverError, PackageManager


def scripted(monkeypatch, module, outputs):
    """Replace a driver module's run_capture with canned stdout keyed by argv[0:2]."""
    calls = []

    async def fake(argv, **kwargs):
        calls.append((argv, kwargs))
        out = outputs[tuple(argv[:2])]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(f"app.core.drivers.{module}.run_capture", fake)
    return calls


# --- Rustup ------------------------------------------------------------------------------------

RUSTUP_CHECK = """\
stable-x86_64-unknown-linux-gnu - Update available : 1.97.0 (2d8144b78 2026-07-07) -> 1.99.1 (58cf8f9c3 2026-10-13)
nightly-x86_64-unknown-linux-gnu - Up to date : 1.100.0-nightly (abc123 2026-10-16)
rustup - Update available : 1.28.2 -> 1.29.1
"""


def test_rustup_check_reports_toolchains_not_rustup_itself():
    assert _parse_check(RUSTUP_CHECK) == [
        {"name": "stable-x86_64-unknown-linux-gnu", "current": "1.97.0", "new": "1.99.1"},
    ]


RUSTUP_129_CHECK = """\
stable-aarch64-unknown-linux-gnu - update available: 1.99.0 (b940084d7 2026-09-28) -> 1.99.1 (58cf8f9c3 2026-10-13)
rustup - up to date : 1.29.1
"""


def test_rustup_129_lowercase_output_and_exit_100_are_updates_not_failures(monkeypatch):
    calls = scripted(monkeypatch, "rustup", {("rustup", "check"): RUSTUP_129_CHECK})
    assert asyncio.run(RustupManager().check_updates()) == [
        {"name": "stable-aarch64-unknown-linux-gnu", "current": "1.99.0", "new": "1.99.1"},
    ]
    assert 100 in calls[0][1]["ok_codes"]


def test_rustup_lists_toolchains_and_never_self_updates(monkeypatch):
    scripted(monkeypatch, "rustup", {("rustup", "toolchain"): "stable-x86_64-unknown-linux-gnu (active, default)\nnightly-x86_64-unknown-linux-gnu\n"})
    assert asyncio.run(RustupManager().list_installed()) == ["stable-x86_64-unknown-linux-gnu", "nightly-x86_64-unknown-linux-gnu"]
    assert RustupManager().get_upgrade_command(["stable"]) == ["rustup", "update", "--no-self-update", "stable"]


# --- Mise --------------------------------------------------------------------------------------

def test_mise_outdated_and_installed(monkeypatch):
    scripted(monkeypatch, "mise", {
        ("mise", "outdated"): json.dumps({
            "node": {"name": "node", "requested": "20", "current": "20.1.0", "latest": "20.11.1"},
            "python": {"name": "python", "requested": "3.12", "current": None, "latest": "3.12.7"},
        }),
        ("mise", "ls"): json.dumps({
            "node": [{"version": "18.0.0"}, {"version": "20.1.0", "active": True}],
            "go": [{"version": "1.23.2"}],
        }),
    })
    mgr = MiseManager()
    # A tool that isn't installed yet (current None) is not an update.
    assert asyncio.run(mgr.check_updates()) == [{"name": "node", "current": "20.1.0", "new": "20.11.1"}]
    assert asyncio.run(mgr.list_installed_versions()) == {"node": "20.1.0", "go": "1.23.2"}


def test_mise_bad_json_is_a_driver_error(monkeypatch):
    scripted(monkeypatch, "mise", {("mise", "outdated"): "not json"})
    with pytest.raises(DriverError):
        asyncio.run(MiseManager().check_updates())


# --- Fisher ------------------------------------------------------------------------------------

def test_fisher_reads_fish_plugins(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "fish").mkdir()
    (tmp_path / "fish" / "fish_plugins").write_text("jorgebucaran/fisher\n\njorgebucaran/nvm.fish\n")
    assert asyncio.run(FisherManager().list_installed()) == ["jorgebucaran/fisher", "jorgebucaran/nvm.fish"]


def test_fisher_without_plugins_file_has_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert asyncio.run(FisherManager().list_installed()) == []


def test_fisher_names_are_argv_not_script_text():
    cmd = FisherManager().get_install_command("evil; rm -rf ~")
    assert cmd[:3] == ["fish", "-c", "fisher install $argv"]
    assert cmd[3] == "--" and cmd[4] == "evil; rm -rf ~"


@pytest.mark.skipif(subprocess.run(["which", "fish"], capture_output=True).returncode != 0, reason="fish not installed")
def test_fish_really_passes_trailing_args_as_argv():
    out = subprocess.run(["fish", "-c", "echo $argv[2]", "--", "a", "b; echo injected"],
                         capture_output=True, text=True).stdout
    assert out == "b; echo injected\n"


# --- Firmware (fwupd) --------------------------------------------------------------------------

FWUPD_UPDATES = json.dumps({"Devices": [
    {"Name": "System Firmware", "DeviceId": "aaaaaaaa1111", "Version": "1.10",
     "Releases": [{"Version": "1.12"}, {"Version": "1.11"}]},
    {"Name": "Dock", "DeviceId": "bbbbbbbb2222", "Version": "3.0", "Releases": [{"Version": "3.1"}]},
    {"Name": "Dock", "DeviceId": "cccccccc3333", "Version": "3.0", "Releases": [{"Version": "3.1"}]},
    {"Name": "No releases", "DeviceId": "dddd", "Version": "1", "Releases": []},
]})


def test_fwupd_updates_map_names_back_to_device_ids(monkeypatch):
    scripted(monkeypatch, "fwupd", {("fwupdmgr", "get-updates"): FWUPD_UPDATES})
    mgr = FwupdManager()
    updates = asyncio.run(mgr.check_updates())
    assert [u["name"] for u in updates] == ["System Firmware", "Dock", "Dock (cccccccc)"]
    assert updates[0] == {"name": "System Firmware", "current": "1.10", "new": "1.12"}
    assert mgr.get_upgrade_command(["System Firmware", "Dock (cccccccc)"]) == \
        ["fwupdmgr", "update", "aaaaaaaa1111", "cccccccc3333"]


def test_fwupd_nothing_to_do_is_an_empty_result(monkeypatch):
    calls = scripted(monkeypatch, "fwupd", {("fwupdmgr", "get-updates"): "No updatable devices\n"})
    assert asyncio.run(FwupdManager().check_updates()) == []
    assert 2 in calls[0][1]["ok_codes"]


def test_fwupd_never_auto_confirms_a_reboot():
    assert "--assume-yes" not in FwupdManager().get_upgrade_command() and "-y" not in FwupdManager().get_upgrade_command()
    assert FwupdManager.asks_for_password


# --- AUR PKGBUILD review -----------------------------------------------------------------------

def test_aur_build_script_uses_package_base(monkeypatch):
    seen = {}

    async def fake_json(url, **k):
        seen["rpc"] = url
        return {"results": [{"Name": "foo-git", "PackageBase": "foo"}]}

    async def fake_capture(argv, **k):
        seen["fetch"] = argv
        return "pkgname=foo-git\nbuild() { make; }\n"

    monkeypatch.setattr("app.core.drivers.aur.fetch_json", fake_json)
    monkeypatch.setattr("app.core.drivers.aur.run_capture", fake_capture)
    url, script = asyncio.run(AurManager().get_build_script("foo-git"))
    assert url.endswith("PKGBUILD?h=foo") and "build()" in script
    assert seen["fetch"][0] == "curl" and seen["fetch"][-1] == url


@pytest.mark.parametrize("name", ["Foo", "a b", "x;rm", "../etc"])
def test_aur_build_script_rejects_invalid_names(name):
    with pytest.raises(DriverError):
        asyncio.run(AurManager().get_build_script(name))


def test_aur_build_script_unknown_package(monkeypatch):
    async def fake_json(url, **k):
        return {"results": []}

    monkeypatch.setattr("app.core.drivers.aur.fetch_json", fake_json)
    with pytest.raises(DriverError, match="not found"):
        asyncio.run(AurManager().get_build_script("nope"))


# --- CLI review --------------------------------------------------------------------------------

class FakeAur(PackageManager):
    name = "FakeAUR"

    def is_available(self):
        return True

    def get_install_command(self, package):
        return ["helper", "-S", package]

    async def get_build_script(self, package):
        if package == "missing":
            raise DriverError("'missing' was not found in the AUR")
        return f"https://aur/{package}", f"pkgname={package}\n"


class Plain(FakeAur):
    name = "Plain"
    get_build_script = PackageManager.get_build_script


@pytest.fixture
def pool(monkeypatch, tmp_path):
    managers = [FakeAur(), Plain()]
    monkeypatch.setattr(cli, "discover_managers", lambda: managers)
    monkeypatch.setattr(cli, "get_all_managers", lambda: managers)
    monkeypatch.setattr(settings_store, "_settings_instance", settings_store.SettingsStore(tmp_path / "s.json"))


def test_review_prints_scripts_and_flags_failures(pool, capsys):
    code = cli.main(["--json", "review", "-m", "fakeaur", "foo", "missing"])
    data = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_FAILED
    assert data[0] == {"package": "foo", "ok": True, "url": "https://aur/foo", "script": "pkgname=foo\n"}
    assert data[1]["ok"] is False and "not found" in data[1]["error"]


def test_review_on_manager_without_scripts_is_usage_error(pool, capsys):
    assert cli.main(["review", "-m", "plain", "x"]) == cli.EXIT_USAGE


def test_install_plan_points_at_review_only_for_script_managers(pool, capsys):
    cli.main(["install", "-m", "fakeaur", "foo"])
    assert "polyget review -m fakeaur foo" in capsys.readouterr().err
    cli.main(["install", "-m", "plain", "foo"])
    assert "review" not in capsys.readouterr().err
