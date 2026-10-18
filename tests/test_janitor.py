"""Janitor: per-driver cleanup targets and `polyget clean`."""

import asyncio
import json
from pathlib import Path

import pytest

import app.cli as cli
import app.core.settings_store as settings_store
from app.core.drivers.dnf import DnfManager
from app.core.drivers.flatpak import FlatpakManager
from app.core.drivers.pacman import PacmanManager, _to_bytes
from app.core.janitor import dir_size, human_size, target
from app.core.manager import DriverError, PackageManager


def scripted(monkeypatch, module, outputs):
    async def fake(argv, **kwargs):
        out = outputs[tuple(argv[:2])]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(f"app.core.drivers.{module}.run_capture", fake)


def test_sizes():
    assert _to_bytes("Installed Size  : 1.50 MiB") == 1572864
    assert _to_bytes("disk space saved: 2 GiB)") == 2 * 1024 ** 3
    assert _to_bytes("nothing") is None
    assert human_size(None) == "?" and human_size(512) == "512 B" and human_size(1536) == "1.5 KiB"


def test_dir_size_counts_files_and_tolerates_missing(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"x" * 50)
    assert asyncio.run(dir_size(tmp_path)) == 150
    assert asyncio.run(dir_size(tmp_path / "missing")) == 0


def test_pacman_orphans_and_paccache(monkeypatch):
    monkeypatch.setattr("app.core.drivers.pacman.shutil.which", lambda b: "/usr/bin/paccache")
    scripted(monkeypatch, "pacman", {
        ("pacman", "-Qdtq"): "libfoo\nlibbar\n",
        ("pacman", "-Qi"): "Name : libfoo\nInstalled Size  : 1.00 MiB\nName : libbar\nInstalled Size  : 512.00 KiB\n",
        ("paccache", "-dk2"): "==> finished dry run: 25 candidates (disk space saved: 1.50 GiB)\n",
    })
    orphans, cache = asyncio.run(PacmanManager().get_cleanup_targets())
    assert orphans["items"] == ["libfoo", "libbar"] and orphans["bytes"] == 1024 ** 2 + 512 * 1024
    assert orphans["command"] == ["pkexec", "pacman", "-Rn", "--noconfirm", "libfoo", "libbar"]
    assert cache["command"] == ["pkexec", "paccache", "-rk2"] and cache["bytes"] == int(1.5 * 1024 ** 3)


def test_pacman_without_orphans_or_paccache(monkeypatch):
    monkeypatch.setattr("app.core.drivers.pacman.shutil.which", lambda b: None)
    scripted(monkeypatch, "pacman", {("pacman", "-Qdtq"): ""})
    (cache,) = asyncio.run(PacmanManager().get_cleanup_targets())
    assert cache["command"] == ["pkexec", "pacman", "-Sc", "--noconfirm"] and cache["bytes"] is None


def test_dnf_autoremove(monkeypatch):
    scripted(monkeypatch, "dnf", {("dnf", "autoremove"):
        "Package  Arch  Version  Repository  Size\nRemoving:\n libfoo  aarch64  1.0-1  fedora  10 KiB\n\nTransaction Summary:\n"})
    monkeypatch.setattr("app.core.drivers.dnf.dir_size", lambda p: asyncio.sleep(0, result=0))
    (orphans,) = asyncio.run(DnfManager().get_cleanup_targets())
    assert orphans["items"] == ["libfoo"] and orphans["command"] == ["pkexec", "dnf", "autoremove", "-y"]


def test_flatpak_offers_only_data_of_uninstalled_apps(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    apps = tmp_path / ".var" / "app"
    for app_id in ("org.kept.App", "org.gone.App"):
        (apps / app_id).mkdir(parents=True)
        (apps / app_id / "config").write_bytes(b"x" * 10)
    scripted(monkeypatch, "flatpak", {("flatpak", "list"): "org.kept.App\norg.gnome.Platform\n"})
    unused, leftover = asyncio.run(FlatpakManager().get_cleanup_targets())
    assert unused["id"] == "unused"
    assert leftover["items"] == ["org.gone.App"] and leftover["bytes"] == 10
    assert leftover["command"] == ["rm", "-rf", "--", str(apps / "org.gone.App")]


def test_flatpak_never_offers_data_when_installed_list_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".var" / "app" / "org.kept.App").mkdir(parents=True)
    scripted(monkeypatch, "flatpak", {("flatpak", "list"): DriverError("flatpak list failed")})
    with pytest.raises(DriverError):
        asyncio.run(FlatpakManager().get_cleanup_targets())


# --- CLI ---------------------------------------------------------------------------------------

class Dirty(PackageManager):
    name = "Dirty"

    def is_available(self):
        return True

    async def get_cleanup_targets(self):
        return [
            target(self.name, "orphans", "Orphans", ["dirty", "autoremove"], 2048, ["a"]),
            target(self.name, "cache", "Cache", ["dirty", "clean"], None),
        ]


class Broken(Dirty):
    name = "Broken"

    async def get_cleanup_targets(self):
        raise DriverError("orphan query failed")


class Clean(Dirty):
    name = "Clean"
    get_cleanup_targets = PackageManager.get_cleanup_targets


@pytest.fixture
def pool(monkeypatch, tmp_path):
    managers = [Dirty(), Broken(), Clean()]
    monkeypatch.setattr(cli, "discover_managers", lambda: managers)
    monkeypatch.setattr(cli, "get_all_managers", lambda: managers)
    monkeypatch.setattr(settings_store, "_settings_instance", settings_store.SettingsStore(tmp_path / "s.json"))


def test_clean_plans_by_default_and_reports_failures(pool, capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: ran.append(a))
    code = cli.main(["--json", "clean"])
    data = json.loads(capsys.readouterr().out)
    assert ran == [] and data["executed"] is False
    assert [t["id"] for t in data["targets"]] == ["orphans", "cache"]
    # Unsupported (Clean) is silent; a failed query (Broken) is an error, never "nothing to clean".
    assert list(data["errors"]) == ["Broken"] and code == cli.EXIT_FAILED


def test_clean_only_filters_and_yes_runs(pool, capsys, monkeypatch):
    class Done:
        returncode = 0

    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **k: calls.append(cmd) or Done())
    code = cli.main(["--json", "clean", "-m", "dirty", "--only", "Dirty:cache", "--yes"])
    data = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK and calls == [["dirty", "clean"]]
    assert data["executed"] is True and data["steps"][0]["success"] is True
