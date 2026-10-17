"""scripts/review-export.sh, exercised with real git in a throwaway repo."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review-export.sh"
BRANCH = "CachyOS/stable-candidate"
TAG = "CachyOS-stable-candidate"

pytestmark = pytest.mark.skipif(not (shutil.which("git") and shutil.which("bash")), reason="needs git and bash")

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, name, text="x"):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


@pytest.fixture
def world(tmp_path):
    repo, review = tmp_path / "repo", tmp_path / "review"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    (repo / "scripts").mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "review-export.sh")
    commit(repo, "base.txt")
    git(repo, "checkout", "-q", "-b", BRANCH)
    commit(repo, "feature.txt", "feature")
    yield repo, review
    if review.exists():  # exports are read-only; let pytest clean up
        subprocess.run(["chmod", "-R", "u+w", str(review)])


def export(repo, review, *args):
    env = {**ENV, "REVIEW_DIR": str(review), "PEER_MOUNT": "/mnt/peer"}
    return subprocess.run(["bash", str(repo / "scripts" / "review-export.sh"), *args],
                          cwd=repo, env=env, capture_output=True, text=True)


def only_export(review):
    return [p for p in review.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")]


def test_export_contains_files_patch_readme_and_is_read_only(world):
    repo, review = world
    result = export(repo, review)
    assert result.returncode == 0, result.stderr
    (out,) = only_export(review)
    assert (out / "files" / "feature.txt").read_text() == "feature"
    assert not (out / "files" / ".git").exists()
    assert "feature.txt" in (out / "candidate-vs-master.patch").read_text()
    readme = (out / "README.txt").read_text()
    assert "/mnt/peer/Projects/_review/" in readme and "noexec" in readme
    with pytest.raises(PermissionError):
        (out / "files" / "new.txt").write_text("nope")


def test_latest_symlink_is_relative_and_points_at_the_export(world):
    repo, review = world
    export(repo, review)
    link = review / f"{TAG}-latest"
    (out,) = only_export(review)
    assert link.is_symlink() and os.readlink(link) == out.name


def test_rerunning_on_an_unchanged_commit_does_nothing(world):
    repo, review = world
    export(repo, review)
    (out,) = only_export(review)
    before = out.stat().st_mtime_ns
    result = export(repo, review)
    assert result.returncode == 0 and "already exported" in result.stdout
    assert out.stat().st_mtime_ns == before


def test_a_new_commit_gets_a_new_export_and_the_old_one_is_removed(world):
    repo, review = world
    export(repo, review)
    (old,) = only_export(review)
    commit(repo, "second.txt", "second")
    result = export(repo, review)
    assert result.returncode == 0 and "removed older export" in result.stdout
    (new,) = only_export(review)
    assert new.name != old.name and not old.exists()
    assert (new / "files" / "second.txt").exists()
    assert os.readlink(review / f"{TAG}-latest") == new.name


def test_keep_retains_older_exports(world):
    repo, review = world
    export(repo, review)
    commit(repo, "second.txt")
    export(repo, review, "--keep")
    assert len(only_export(review)) == 2


def test_pruning_never_touches_a_lookalike_directory(world):
    repo, review = world
    export(repo, review)
    lookalike = review / f"{TAG}-notes"
    lookalike.mkdir()
    commit(repo, "second.txt")
    export(repo, review)
    assert lookalike.exists()


def test_report_and_tested_text_are_included(world, tmp_path):
    repo, review = world
    report = tmp_path / "r.md"
    report.write_text("# what is going on")
    result = export(repo, review, "--report", str(report), "--tested", "330 passed on CachyOS")
    assert result.returncode == 0, result.stderr
    (out,) = only_export(review)
    assert (out / "REPORT.md").read_text() == "# what is going on"
    assert "330 passed on CachyOS" in (out / "README.txt").read_text()


def test_force_rebuilds_an_already_exported_commit(world, tmp_path):
    repo, review = world
    export(repo, review)
    report = tmp_path / "r.md"
    report.write_text("late report")
    result = export(repo, review, "--force", "--report", str(report))
    assert result.returncode == 0
    (out,) = only_export(review)
    assert (out / "REPORT.md").exists()


def test_unknown_branch_fails_cleanly(world):
    repo, review = world
    result = export(repo, review, "no/such-branch")
    assert result.returncode != 0 and "no such branch" in result.stderr
    assert not review.exists() or not only_export(review)


def test_governance_files_in_a_candidate_trigger_a_warning(world):
    repo, review = world
    commit(repo, "BRANCHING.md", "rules")
    result = export(repo, review)
    assert result.returncode == 0 and "BRANCHING.md is in this export" in result.stderr
