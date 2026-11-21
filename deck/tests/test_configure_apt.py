import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CONFIGURE_APT = HERE / "configure-apt.sh"


def test_configure_apt_list():
    res = subprocess.run([str(CONFIGURE_APT), "list"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "Pixel 10 Pro" in res.stdout
    assert "termux-main" in res.stdout
    assert "tur-repo" in res.stdout


def test_configure_apt_enable_and_dryrun():
    with tempfile.TemporaryDirectory() as tmpdir:
        conf_file = os.path.join(tmpdir, "99pixel-deck")
        stage_dir = os.path.join(tmpdir, "stage")
        sources_dir = os.path.join(tmpdir, "sources.list.d")
        os.makedirs(sources_dir, exist_ok=True)

        # Stage enable tur-repo
        cmd = [
            str(CONFIGURE_APT),
            "enable", "tur-repo",
            "--conf", conf_file,
            "--stage-dir", stage_dir,
            "--sources-dir", sources_dir,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert "Dry run passed and stamped" in res.stdout
        assert "enable  tur-repo" in res.stdout

        # Verify staged files exist
        assert os.path.isfile(os.path.join(stage_dir, "apt.conf.staged"))
        assert os.path.isfile(os.path.join(stage_dir, "repo-plan.txt"))

        # Now test apply
        apply_cmd = [
            str(CONFIGURE_APT),
            "apply",
            "--conf", conf_file,
            "--stage-dir", stage_dir,
            "--sources-dir", sources_dir,
        ]
        res_apply = subprocess.run(apply_cmd, capture_output=True, text=True)
        assert res_apply.returncode == 0
        assert "applied successfully" in res_apply.stdout or "Dry run passed" in res_apply.stdout


def test_configure_apt_add_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        conf_file = os.path.join(tmpdir, "99pixel-deck")
        stage_dir = os.path.join(tmpdir, "stage")
        sources_dir = os.path.join(tmpdir, "sources.list.d")
        catalog_file = os.path.join(tmpdir, "test.catalog")
        shutil.copy2(HERE / "termux-repos.catalog", catalog_file)
        os.makedirs(sources_dir, exist_ok=True)

        cmd = [
            str(CONFIGURE_APT),
            "add-repo", "my-test-repo", "deb https://example.com/apt stable main",
            "--conf", conf_file,
            "--stage-dir", stage_dir,
            "--sources-dir", sources_dir,
            "--catalog", catalog_file,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert "staged for enablement" in res.stdout
        assert "my-test-repo" in Path(catalog_file).read_text()
