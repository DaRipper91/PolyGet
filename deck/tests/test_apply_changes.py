"""Regression tests for apply_changes(): exit-code handling, sudo, pipelines.

Everything runs in a tmp dir with subprocess.run faked, so no real sudo/dnf
is ever invoked.
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "asahi_deck", Path(__file__).resolve().parent.parent / "asahi-deck.py")
ad = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ad)

CATALOG = """\
[testbuiltin]
cat: Test
kind: builtin
ids: fedora-cisco-openh264
top: x
info: builtin test repo

[testinline]
cat: Test
kind: repofile-inline
file: /etc/yum.repos.d/testinline.repo
ids: testinline
content: [testinline]\\nname=T\\nbaseurl=https://example.invalid\\nenabled=1\\ngpgcheck=1
top: x
info: inline test repo
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    conf = tmp_path / "dnf.conf"
    conf.write_text("[main]\ngpgcheck=True\nfastestmirror=False\n")
    repos = tmp_path / "repos.d"
    repos.mkdir()
    cat = tmp_path / "repos.catalog"
    cat.write_text(CATALOG)
    calls = []
    fail = {"match": None}

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        # let the real cp/install touch the tmp files; fake everything else
        if cmd[0] in ("cp", "install"):
            return real_run(cmd, **kw)
        rc = 1 if fail["match"] and fail["match"] in " ".join(cmd) else 0
        return subprocess.CompletedProcess(cmd, rc, "", "boom" if rc else "")

    real_run = subprocess.run
    monkeypatch.setattr(ad.subprocess, "run", fake_run)
    monkeypatch.setattr(ad.shutil, "which", lambda _n: None)  # skip dnf validation
    monkeypatch.setattr(ad, "is_root", lambda: False)
    return conf, repos, cat, calls, fail


def make_state(env):
    conf, repos, cat, _, _ = env
    st = ad.State(str(conf), str(repos), str(cat))
    return st


def test_run_cmd_returns_exit_code():
    assert ad.run_cmd(["true"], lambda _s: None) == 0
    assert ad.run_cmd(["false"], lambda _s: None) == 1


def test_apply_succeeds_and_writes_conf_and_backup(env):
    conf = env[0]
    st = make_state(env)
    st.set_option("fastestmirror", "True")
    st.reviewed_hash = st.fingerprint()
    logs = []
    assert ad.apply_changes(st, logs.append, confirm=lambda _m: "y") is True
    assert "fastestmirror=True" in conf.read_text()
    assert len(list(conf.parent.glob("dnf.conf.bak-*"))) == 1
    assert not any("backup failed" in line for line in logs)


def test_repo_commands_have_single_sudo_and_are_logged_once(env):
    calls = env[3]
    st = make_state(env)
    st.toggle("testbuiltin")
    st.reviewed_hash = st.fingerprint()
    logs = []
    assert ad.apply_changes(st, logs.append, confirm=lambda _m: "y") is True
    dnf_calls = [c for c in calls if "config-manager" in c]
    assert dnf_calls and all(c[:2] == ["sudo", "dnf"] for c in dnf_calls)
    assert sum("config-manager" in line for line in logs) == len(dnf_calls)


def test_failed_repo_command_aborts_apply(env):
    conf = env[0]
    fail = env[4]
    fail["match"] = "config-manager"
    st = make_state(env)
    st.set_option("fastestmirror", "True")
    st.toggle("testbuiltin")
    st.reviewed_hash = st.fingerprint()
    logs = []
    assert ad.apply_changes(st, logs.append, confirm=lambda _m: "y") is False
    assert any("command failed" in line for line in logs)
    assert any("rolled back dnf.conf to backup" in line for line in logs)
    assert "fastestmirror=False" in conf.read_text()
    assert "fastestmirror=True" not in conf.read_text()


def test_inline_repofile_pipeline_runs_through_a_shell(env):
    calls = env[3]
    st = make_state(env)
    st.toggle("testinline")
    st.reviewed_hash = st.fingerprint()
    assert ad.apply_changes(st, lambda _s: None, confirm=lambda _m: "y") is True
    shell_calls = [c for c in calls if c[:2] == ["bash", "-c"]]
    assert any("tee" in c[2] and "testinline.repo" in c[2] for c in shell_calls)
