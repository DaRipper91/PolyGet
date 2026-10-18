"""Restart-needed detection: distro query first, then the generic checks."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.cli as cli
import app.core.restart as restart


class FakeProc:
    def __init__(self, code, out=b"", err=b""):
        self.returncode, self._out, self._err = code, out, err

    async def communicate(self):
        return self._out, self._err


@pytest.fixture
def no_generic(monkeypatch, tmp_path):
    """No Debian flag, no modules dir, unless a test creates them."""
    monkeypatch.setattr(restart, "_DEBIAN_FLAG", tmp_path / "reboot-required")
    monkeypatch.setattr(restart, "_MODULES_DIR", tmp_path / "modules")
    monkeypatch.setattr(restart, "get_reboot_check_command", lambda: None)
    monkeypatch.setattr(restart, "replaces_running_kernel", lambda: False)
    return tmp_path


def use_command(monkeypatch, proc):
    monkeypatch.setattr(restart, "get_reboot_check_command", lambda: ["dnf", "needs-restarting", "-r"])

    async def fake_exec(*argv, **k):
        return proc

    monkeypatch.setattr(restart.asyncio, "create_subprocess_exec", fake_exec)


DNF_REBOOT = b"""Core libraries or services have been updated since boot-up:
  * kernel
  * systemd

Reboot is required to fully utilize these updates.
"""


def test_dnf_says_reboot(no_generic, monkeypatch):
    use_command(monkeypatch, FakeProc(1, DNF_REBOOT))
    result = asyncio.run(restart.check_restart_needed())
    assert result["needed"] is True and result["reasons"] == ["kernel", "systemd"]


def test_dnf_says_no_reboot(no_generic, monkeypatch):
    use_command(monkeypatch, FakeProc(0, b"No core libraries or services have been updated since boot-up.\n"))
    assert asyncio.run(restart.check_restart_needed())["needed"] is False


def test_missing_dnf_plugin_is_not_a_reboot(no_generic, monkeypatch):
    use_command(monkeypatch, FakeProc(1, b"", b"No such command: needs-restarting."))
    assert asyncio.run(restart.check_restart_needed())["needed"] is None


def test_arch_kernel_replaced(no_generic, monkeypatch):
    monkeypatch.setattr(restart, "replaces_running_kernel", lambda: True)
    monkeypatch.setattr(restart.os, "uname", lambda: SimpleNamespace(release="6.11.1-cachyos"))
    (no_generic / "modules" / "6.11.5-cachyos").mkdir(parents=True)
    result = asyncio.run(restart.check_restart_needed())
    assert result["needed"] is True and "6.11.5-cachyos" in result["reasons"][0]
    (no_generic / "modules" / "6.11.1-cachyos").mkdir()
    assert asyncio.run(restart.check_restart_needed())["needed"] is False


def test_kernel_check_skipped_where_old_kernels_stay(no_generic, monkeypatch):
    # Fedora keeps the old kernel installed; a modules-dir check there would always say "no".
    (no_generic / "modules" / "something-else").mkdir(parents=True)
    assert asyncio.run(restart.check_restart_needed())["needed"] is None


def test_debian_flag(no_generic):
    (no_generic / "reboot-required").write_text("*** System restart required ***\n")
    (no_generic / "reboot-required.pkgs").write_text("linux-image-6.8\nlibc6\n")
    result = asyncio.run(restart.check_restart_needed())
    assert result["needed"] is True and "libc6" in result["reasons"][0]


def test_cli_needs_restart(monkeypatch, capsys):
    async def fake():
        return {"needed": True, "method": "test", "reasons": ["kernel"]}

    monkeypatch.setattr(restart, "check_restart_needed", fake)
    assert cli.main(["--json", "needs-restart"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["needed"] is True
