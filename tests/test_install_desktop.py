"""scripts/install-desktop.sh must turn the repo's template desktop file into a launcher with this checkout's real paths."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


@pytest.fixture
def fake_checkout(tmp_path):
    """A copy of the installer, template and icons next to a stand-in .venv interpreter, with a throwaway HOME."""
    repo, home = tmp_path / "checkout", tmp_path / "home"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "install-desktop.sh", repo / "scripts")
    shutil.copytree(ROOT / "assets", repo / "assets")
    (repo / ".venv" / "bin").mkdir(parents=True)
    python = repo / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    home.mkdir()
    return repo, home


def install(repo, home, *args):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(["bash", str(repo / "scripts" / "install-desktop.sh"), *args], env=env, capture_output=True, text=True)


def test_template_has_no_personal_or_machine_specific_path():
    text = (ROOT / "assets" / "polyget.desktop").read_text()
    assert "/home/" not in text and "Polyget/" not in text  # the wrong-case checkout path it used to hard-code


def test_installer_bakes_the_checkouts_real_paths_into_the_launcher(fake_checkout):
    repo, home = fake_checkout
    result = install(repo, home)
    assert result.returncode == 0, result.stderr
    entry = (home / ".local" / "share" / "applications" / "polyget.desktop").read_text()
    assert f"Exec={repo}/.venv/bin/python {repo}/run.py %f" in entry
    assert f"TryExec={repo}/.venv/bin/python" in entry
    assert "/path/to/PolyGet" not in entry
    assert (home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "polyget.svg").is_file()


def test_installer_refuses_without_a_venv_interpreter(fake_checkout):
    repo, home = fake_checkout
    shutil.rmtree(repo / ".venv")
    result = install(repo, home)
    assert result.returncode != 0 and "no interpreter" in result.stderr


def test_uninstall_removes_the_launcher(fake_checkout):
    repo, home = fake_checkout
    install(repo, home)
    result = install(repo, home, "--uninstall")
    assert result.returncode == 0
    assert not (home / ".local" / "share" / "applications" / "polyget.desktop").exists()
