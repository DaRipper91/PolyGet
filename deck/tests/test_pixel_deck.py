import os
import tempfile
import pytest
from pathlib import Path

# Import pixel-deck modules
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import importlib
pixel_deck = importlib.import_module("pixel-deck")
CatalogEntry = pixel_deck.CatalogEntry
load_catalog = pixel_deck.load_catalog
AptConf = pixel_deck.AptConf
scan_termux_repos = pixel_deck.scan_termux_repos
State = pixel_deck.State
OPTIONS = pixel_deck.OPTIONS
RECOMMENDED = pixel_deck.RECOMMENDED
REQUIRED = pixel_deck.REQUIRED
REFUSED = pixel_deck.REFUSED


@pytest.fixture
def catalog_path():
    p = Path(__file__).resolve().parent.parent / "termux-repos.catalog"
    assert p.is_file()
    return str(p)


@pytest.fixture
def temp_env(catalog_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        conf_path = os.path.join(tmpdir, "99pixel-deck")
        sources_dir = os.path.join(tmpdir, "sources.list.d")
        sources_list = os.path.join(tmpdir, "sources.list")
        os.makedirs(sources_dir, exist_ok=True)
        
        with open(sources_list, "w") as f:
            f.write("deb https://packages-cf.termux.dev/apt/termux-main stable main\n")
            
        yield {
            "conf_path": conf_path,
            "sources_dir": sources_dir,
            "sources_list": sources_list,
            "catalog_path": catalog_path,
            "tmpdir": tmpdir,
        }


def test_load_catalog(catalog_path):
    catalog = load_catalog(catalog_path)
    assert len(catalog) > 10
    assert "termux-main" in catalog
    assert catalog["termux-main"].is_required()
    assert not catalog["termux-main"].is_refused()
    
    assert "debian-raw-ppa" in catalog
    assert catalog["debian-raw-ppa"].has_warning()
    assert not catalog["debian-raw-ppa"].is_refused()
    
    assert "termux-x11" in catalog
    assert catalog["termux-x11"].pkg == "x11-repo"
    assert "x11-repo" in catalog["termux-x11"].id_list


def test_scan_termux_repos(temp_env):
    sources_dir = temp_env["sources_dir"]
    sources_list = temp_env["sources_list"]
    
    # Write a custom repo in sources.list.d
    with open(os.path.join(sources_dir, "tur.list"), "w") as f:
        f.write("deb https://tur.kcubeterm.me/tur-packages tur main\n")
        
    active = scan_termux_repos(sources_dir, sources_list)
    assert "termux-main" in active
    assert "termux-main-cf" in active
    assert "tur" in active


def test_state_initialization(temp_env):
    state = State(
        temp_env["conf_path"],
        temp_env["sources_dir"],
        temp_env["sources_list"],
        temp_env["catalog_path"],
    )
    
    assert state.is_on("termux-main")
    assert not state.is_on("debian-raw-ppa")
    assert state.changes_count() == 0


def test_state_toggle_and_guardrails(temp_env):
    state = State(
        temp_env["conf_path"],
        temp_env["sources_dir"],
        temp_env["sources_list"],
        temp_env["catalog_path"],
    )
    
    # Advisory repos (e.g. debian-raw-ppa) can be toggled without hard refusal, with advisory returned
    err = state.toggle("debian-raw-ppa")
    assert "Advisory" in err or "warn" in err.lower()
    assert state.is_on("debian-raw-ppa")
    
    # Cannot disable required repo
    err = state.toggle("termux-main")
    assert "required" in err.lower()
    assert state.is_on("termux-main")
    
    # Can toggle optional repo
    prev_state = state.is_on("tur-repo")
    err = state.toggle("tur-repo")
    assert err == ""
    assert state.is_on("tur-repo") != prev_state
    assert state.changes_count() >= 1


def test_state_add_custom_repo(temp_env):
    state = State(
        temp_env["conf_path"],
        temp_env["sources_dir"],
        temp_env["sources_list"],
        temp_env["catalog_path"],
    )
    ok, msg = state.add_custom_repo("my-custom-ppa", "https://example.com/repo stable main")
    assert ok
    assert "my-custom-ppa" in state.catalog
    assert state.is_on("my-custom-ppa")
    assert state.changes_count() >= 1

    cmds = state.repo_cmds("my-custom-ppa", True)
    assert len(cmds) == 1
    assert "deb [trusted=yes] https://example.com/repo stable main" in cmds[0]
    assert "my-custom-ppa.list" in cmds[0]


def test_state_options_management(temp_env):
    state = State(
        temp_env["conf_path"],
        temp_env["sources_dir"],
        temp_env["sources_list"],
        temp_env["catalog_path"],
    )
    
    # Check default recommended option
    opt_val = state.option_value("Acquire::AllowInsecureRepositories")
    assert opt_val == "false"
    
    # Set override
    state.set_option("Acquire::http::Timeout", "30")
    assert state.option_value("Acquire::http::Timeout") == "30"
    assert state.changes_count() >= 1
    
    # Unset option
    state.unset_option("Acquire::http::Timeout")
    assert state.option_value("Acquire::http::Timeout") == RECOMMENDED["Acquire::http::Timeout"]


def test_apt_conf_render(temp_env):
    state = State(
        temp_env["conf_path"],
        temp_env["sources_dir"],
        temp_env["sources_list"],
        temp_env["catalog_path"],
    )
    rendered = state.proposed_conf()
    assert 'Acquire::AllowInsecureRepositories "false";' in rendered
    assert 'Acquire::Languages "none";' in rendered
    assert 'DPkg::Options {' in rendered
    
    diff = state.diff_text()
    assert diff != ""


def test_repo_cmds_generation(temp_env):
    state = State(
        temp_env["conf_path"],
        temp_env["sources_dir"],
        temp_env["sources_list"],
        temp_env["catalog_path"],
    )
    
    cmds_enable = state.repo_cmds("termux-x11", enable=True)
    assert any("x11-repo" in c for c in cmds_enable)
    
    cmds_disable = state.repo_cmds("termux-x11", enable=False)
    assert any("uninstall" in c or "remove" in c for c in cmds_disable)
    
    cmds_tor = state.repo_cmds("tor-repo", enable=True)
    assert any("tor-repo.list" in c for c in cmds_tor)


def test_stage_and_apply(temp_env):
    state = State(
        temp_env["conf_path"],
        temp_env["sources_dir"],
        temp_env["sources_list"],
        temp_env["catalog_path"],
    )
    stage_dir = os.path.join(temp_env["tmpdir"], "stage")
    
    # Toggle an option and a repo
    state.set_option("Acquire::http::Pipeline-Depth", "10")
    state.toggle("tur-repo")
    
    # Stage plan
    state.stage_plan(stage_dir)
    assert os.path.isfile(os.path.join(stage_dir, "apt.conf.staged"))
    assert os.path.isfile(os.path.join(stage_dir, "repo-plan.txt"))
    
    with open(os.path.join(stage_dir, "repo-plan.txt")) as f:
        plan_content = f.read()
    assert "tur-repo" in plan_content
    
    # Apply dry-run gate check
    state.reviewed = True
    logs = []
    ok = state.apply_changes(log=logs.append, dry_run=True)
    assert ok is True
    assert any("dry-run" in line.lower() or "passed" in line.lower() or "staged" in line.lower() for line in logs)


# ---------------------------------------------------------------- real apply ---
import subprocess  # noqa: E402


def _fake_run(monkeypatch, fail_on=None):
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        rc = 1 if fail_on and fail_on in str(cmd) else 0
        return subprocess.CompletedProcess(cmd, rc, "", "boom" if rc else "")

    monkeypatch.setattr(pixel_deck.subprocess, "run", fake)
    return calls


def _state(temp_env):
    return State(temp_env["conf_path"], temp_env["sources_dir"],
                 temp_env["sources_list"], temp_env["catalog_path"])


def test_apply_requires_review(temp_env, monkeypatch):
    state = _state(temp_env)
    calls = _fake_run(monkeypatch)
    state.set_option("Acquire::http::Pipeline-Depth", "10")
    logs = []
    assert state.apply_changes(log=logs.append, dry_run=False) is False
    assert calls == []
    assert not os.path.exists(temp_env["conf_path"])


def test_apply_writes_conf_and_runs_repo_cmds(temp_env, monkeypatch):
    calls = _fake_run(monkeypatch)
    state = _state(temp_env)
    state.set_option("Acquire::http::Pipeline-Depth", "10")
    state.toggle("tur-repo")
    state.reviewed = True
    assert state.apply_changes(log=lambda _s: None, dry_run=False) is True
    assert "Pipeline-Depth" in open(temp_env["conf_path"]).read()
    assert any("tur-repo" in str(c) for c in calls)


def test_failed_repo_command_fails_apply_and_restores_conf(temp_env, monkeypatch):
    with open(temp_env["conf_path"], "w") as f:
        f.write('Acquire::Retries "3";\n')
    before = open(temp_env["conf_path"]).read()
    _fake_run(monkeypatch, fail_on="tur-repo")
    state = _state(temp_env)
    state.set_option("Acquire::http::Pipeline-Depth", "10")
    state.toggle("tur-repo")
    state.reviewed = True
    logs = []
    assert state.apply_changes(log=logs.append, dry_run=False) is False
    assert open(temp_env["conf_path"]).read() == before
    assert any("NOT rolled back" in line for line in logs)
    assert not any("All repository mutations complete" in line for line in logs)
