"""repo-check.sh and the pre-push guard, exercised with real git against two simulated machines.

A bare repo stands in for GitHub; `asahi` and `cachy` are clones of it. Each scenario engineers one
kind of drift and asserts the script's exit status (0 clean, 1 review suggested, 2 alert).
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "repo-check.sh"
HOOK = ROOT / "scripts" / "git-hooks" / "pre-push"
BETA = "CachyOS/BETA-FEATURES"

pytestmark = pytest.mark.skipif(not (shutil.which("git") and shutil.which("bash")), reason="needs git and bash")

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=check)


def commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name)
    git(cwd, "add", name)
    git(cwd, "commit", "-qm", name)


@pytest.fixture
def machines(tmp_path):
    """A clean world: `cachy` has a beta branch in sync with its remote and containing master."""
    git(tmp_path, "init", "-q", "--bare", "-b", "master", "origin.git")
    for name in ("asahi", "cachy"):
        git(tmp_path, "clone", "-q", "origin.git", name)
    asahi, cachy = tmp_path / "asahi", tmp_path / "cachy"
    # master already carries the script, as it will once the beta branch has been promoted.
    (asahi / "scripts").mkdir()
    shutil.copy(CHECK, asahi / "scripts" / "repo-check.sh")
    git(asahi, "add", "scripts")
    commit(asahi, "base")
    git(asahi, "push", "-q", "origin", "master")
    git(cachy, "pull", "-q", "origin", "master")
    git(cachy, "checkout", "-q", "-b", BETA)
    commit(cachy, "beta")
    git(cachy, "push", "-q", "-u", "origin", BETA)
    return asahi, cachy


def check(cachy: Path, *flags: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["bash", str(cachy / "scripts" / "repo-check.sh"), "--no-fetch", *flags],
        cwd=cachy, env=ENV, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def advance_remote_master(asahi: Path, cachy: Path) -> None:
    commit(asahi, f"adv-{len(list(asahi.iterdir()))}")
    git(asahi, "push", "-q", "origin", "master")
    git(cachy, "fetch", "-q", "origin")


def test_clean_clone_exits_zero(machines):
    _, cachy = machines
    code, out = check(cachy)
    assert code == 0 and "RESULT: clean" in out


def test_master_drift_with_a_synced_beta_suggests_a_review(machines):
    asahi, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    advance_remote_master(asahi, cachy)
    code, out = check(cachy)
    assert code == 1
    assert "does NOT match origin/master" in out and "A beta in sync can hide a drifted master" in out


def test_local_master_ahead_is_an_alert_normally_but_fine_when_promoting(machines):
    _, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    git(cachy, "checkout", "-q", "master")
    commit(cachy, "local-master")
    git(cachy, "checkout", "-q", BETA)
    code, out = check(cachy)
    assert code == 2 and "Do not merge into master" in out
    code, out = check(cachy, "--promoting")
    assert "ready to push" in out and "ALERT local master" not in out


def test_diverged_master_is_an_alert_in_both_modes(machines):
    asahi, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    advance_remote_master(asahi, cachy)
    git(cachy, "checkout", "-q", "master")
    commit(cachy, "local-master")
    git(cachy, "checkout", "-q", BETA)
    for flags in ((), ("--promoting",)):
        code, out = check(cachy, *flags)
        assert code == 2 and "DIVERGED from origin/master" in out


def test_behind_master_is_a_warning_normally_but_an_alert_when_promoting(machines):
    asahi, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    advance_remote_master(asahi, cachy)
    assert check(cachy)[0] == 1
    code, out = check(cachy, "--promoting")
    assert code == 2 and "a push would be rejected" in out


def test_unpushed_commit_and_uncommitted_file_are_warnings(machines):
    _, cachy = machines
    commit(cachy, "unpushed")
    code, out = check(cachy)
    assert code == 1 and "unpushed commit" in out
    (cachy / "scratch.txt").write_text("wip")
    assert "uncommitted" in check(cachy)[1]


def test_beta_diverged_from_its_own_remote_is_an_alert(machines):
    _, cachy = machines
    git(cachy, "reset", "-q", "--hard", "HEAD~1")
    commit(cachy, "different")
    code, out = check(cachy)
    assert code == 2 and f"DIVERGED from origin/{BETA}" in out


def push_master(cachy: Path, override: bool, *extra: str) -> subprocess.CompletedProcess:
    hooks = cachy / ".git" / "hooks"
    shutil.copy(HOOK, hooks / "pre-push")
    (hooks / "pre-push").chmod(0o755)
    args = ["-c", "polyget.allowMasterPush=true"] if override else []
    return git(cachy, *args, "push", *extra, "origin", "master", check=False)


def test_pre_push_blocks_master_without_a_deliberate_override(machines):
    _, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    git(cachy, "checkout", "-q", "master")
    commit(cachy, "promote-me")
    result = push_master(cachy, override=False)
    assert result.returncode != 0 and "needs to be deliberate" in result.stderr


def test_pre_push_override_allows_a_clean_fast_forward(machines):
    _, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    git(cachy, "checkout", "-q", "master")
    commit(cachy, "promote-me")
    result = push_master(cachy, override=True)
    assert result.returncode == 0, result.stderr


def _stale_master(machines):
    asahi, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    advance_remote_master(asahi, cachy)
    git(cachy, "checkout", "-q", "master")
    commit(cachy, "stale-promote")
    return cachy


def test_git_itself_rejects_an_ordinary_push_of_a_stale_master(machines):
    # git refuses non-fast-forward pushes before pre-push runs, so the hook is never reached.
    result = push_master(_stale_master(machines), override=True)
    assert result.returncode != 0 and "non-fast-forward" in result.stderr


def test_pre_push_override_still_refuses_a_forced_push_when_repo_check_alerts(machines):
    # --force gets past git's own check, which is exactly when the repo check has to hold the line.
    cachy = _stale_master(machines)
    result = push_master(cachy, True, "--force")
    assert result.returncode != 0 and "repo-check raised an ALERT" in result.stderr
    assert git(cachy, "ls-remote", "origin", "refs/heads/master").stdout.split()[0] != git(cachy, "rev-parse", "master").stdout.strip()


def test_pre_push_never_blocks_the_beta_branch(machines):
    _, cachy = machines
    commit(cachy, "more-beta")
    shutil.copy(HOOK, cachy / ".git" / "hooks" / "pre-push")
    (cachy / ".git" / "hooks" / "pre-push").chmod(0o755)
    assert git(cachy, "push", "origin", BETA, check=False).returncode == 0


def test_pre_push_fails_closed_when_the_check_script_is_missing(machines):
    # Pushing master from a checkout that predates repo-check.sh must not silently skip the check.
    _, cachy = machines
    git(cachy, "branch", "master", "origin/master", check=False)
    git(cachy, "checkout", "-q", "master")
    commit(cachy, "promote-me")
    (cachy / "scripts" / "repo-check.sh").unlink()
    git(cachy, "commit", "-qam", "drop the script")
    result = push_master(cachy, override=True)
    assert result.returncode != 0 and "cannot be verified" in result.stderr
