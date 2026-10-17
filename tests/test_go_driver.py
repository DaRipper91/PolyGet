import asyncio
import subprocess
from unittest.mock import patch

import pytest

from app.core.drivers import go as go_mod
from app.core.drivers.go import GoManager
from app.core.manager import DriverError

BUILD_INFO = (
    "{exe}: go1.23.0\n\tpath\tgolang.org/x/tools/gopls\n\tmod\tgolang.org/x/tools/gopls\tv0.16.1\th1:abc=\n"
)


def _fake_run(outputs):
    def run(argv, **kwargs):
        exe = argv[-1]
        text, rc = outputs.get(exe.rsplit("/", 1)[-1], ("", 1))
        return subprocess.CompletedProcess(argv, rc, stdout=text, stderr="")
    return run


def test_scan_reads_embedded_build_info_and_skips_non_go_files(tmp_path):
    for name in ("gopls", "notgo", "built-locally"):
        exe = tmp_path / name
        exe.write_text("x")
        exe.chmod(0o755)
    (tmp_path / "readme.txt").write_text("not executable")
    outputs = {
        "gopls": (BUILD_INFO, 0),
        "notgo": ("", 1),
        "built-locally": ("x\n\tpath\tcommand-line-arguments\n\tmod\tx\t(devel)\n", 0),
    }
    with patch.object(go_mod, "_go_bin_dir", return_value=tmp_path), \
         patch.object(go_mod.subprocess, "run", _fake_run(outputs)):
        assert go_mod._scan_binaries() == {"golang.org/x/tools/gopls": ("golang.org/x/tools/gopls", "v0.16.1")}


def test_scan_missing_bin_dir_is_empty(tmp_path):
    with patch.object(go_mod, "_go_bin_dir", return_value=tmp_path / "absent"):
        assert go_mod._scan_binaries() == {}


def test_go_bin_dir_prefers_gobin_then_first_gopath_entry():
    def run(out):
        return patch.object(go_mod.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=out))
    with run("/opt/gobin\n/home/u/go\n"):
        assert str(go_mod._go_bin_dir()) == "/opt/gobin"
    with run("\n/home/u/go:/other\n"):
        assert str(go_mod._go_bin_dir()) == "/home/u/go/bin"


def test_check_updates_flags_only_changed_versions(scripted_exec):
    scripted_exec.add("golang.org/x/tools/gopls@latest", stdout="v0.17.0\n")
    scripted_exec.add("example.com/tool@latest", stdout="v1.0.0\n")
    found = {"golang.org/x/tools/gopls": ("golang.org/x/tools/gopls", "v0.16.1"),
             "example.com/tool/cmd": ("example.com/tool", "v1.0.0")}
    with patch.object(go_mod, "_scan_binaries", return_value=found):
        updates = asyncio.run(GoManager().check_updates())
    assert updates == [{"name": "golang.org/x/tools/gopls", "current": "v0.16.1", "new": "v0.17.0"}]


def test_check_updates_all_lookups_failing_raises(scripted_exec):
    scripted_exec.add("go list", rc=1, stderr="proxy unreachable")
    with patch.object(go_mod, "_scan_binaries", return_value={"a/b": ("a/b", "v1.0.0")}):
        with pytest.raises(DriverError):
            asyncio.run(GoManager().check_updates())


def test_upgrade_command_uses_package_paths():
    mgr = GoManager()
    assert mgr.get_upgrade_command(["a/b/cmd"]) == ["go", "install", "a/b/cmd@latest"]
    with patch.object(go_mod, "_scan_binaries", return_value={"x/y": ("x", "v1")}):
        assert mgr.get_upgrade_command() == ["go", "install", "x/y@latest"]
    with patch.object(go_mod, "_scan_binaries", return_value={}):
        with pytest.raises(DriverError):
            mgr.get_upgrade_command()


def test_install_appends_latest_only_when_unpinned():
    assert GoManager().get_install_command("a/b") == ["go", "install", "a/b@latest"]
    assert GoManager().get_install_command("a/b@v1.2.3") == ["go", "install", "a/b@v1.2.3"]
