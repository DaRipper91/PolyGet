import asyncio
import json

import pytest

from app.core.drivers.bun import BunManager
from app.core.drivers.deno import DenoManager


@pytest.fixture
def bun_home(tmp_path, monkeypatch):
    monkeypatch.setenv("BUN_INSTALL", str(tmp_path))
    return tmp_path / "install" / "global"


def _write_global(root, deps):
    root.mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"dependencies": {n: "^1" for n in deps}}))
    for name, version in deps.items():
        pkg = root / "node_modules" / name
        pkg.mkdir(parents=True)
        (pkg / "package.json").write_text(json.dumps({"version": version}))


def test_bun_without_global_dir_reports_nothing_instead_of_falling_back_to_cwd(bun_home, scripted_exec):
    # `bun pm ls -g` would list the cwd's node_modules here; the driver must not shell out at all.
    assert asyncio.run(BunManager().list_installed_versions()) == {}
    assert scripted_exec.calls == []


def test_bun_reads_installed_versions_from_disk(bun_home):
    _write_global(bun_home, {"@scope/tool": "1.2.0", "left-pad": "1.3.0"})
    assert asyncio.run(BunManager().list_installed_versions()) == {"@scope/tool": "1.2.0", "left-pad": "1.3.0"}


def test_bun_check_updates_encodes_scoped_names(bun_home, scripted_exec):
    _write_global(bun_home, {"@scope/tool": "1.2.0", "left-pad": "1.3.0"})
    scripted_exec.add("registry.npmjs.org/@scope%2Ftool/latest", stdout='{"version": "1.3.0"}')
    scripted_exec.add("registry.npmjs.org/left-pad/latest", stdout='{"version": "1.3.0"}')
    assert asyncio.run(BunManager().check_updates()) == [{"name": "@scope/tool", "current": "1.2.0", "new": "1.3.0"}]


def test_bun_commands():
    mgr = BunManager()
    assert mgr.get_upgrade_command() == ["bun", "update", "-g"]
    assert mgr.get_upgrade_command(["a"]) == ["bun", "update", "-g", "a"]
    assert mgr.get_install_command("a") == ["bun", "add", "-g", "a"]


def test_deno_lists_scripts_with_pinned_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("DENO_INSTALL_ROOT", str(tmp_path))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "file_server").write_text('exec deno "run" "jsr:@std/http@1.0.2/file-server" "$@"\n')
    (bin_dir / "adhoc").write_text('exec deno "run" "https://example.com/x.ts" "$@"\n')
    (bin_dir / "deno").write_text("the runtime itself")
    assert asyncio.run(DenoManager().list_installed_versions()) == {"file_server": "1.0.2", "adhoc": ""}


def test_deno_update_and_upgrade_are_unsupported_not_clean():
    mgr = DenoManager()
    with pytest.raises(NotImplementedError):
        asyncio.run(mgr.check_updates())
    with pytest.raises(NotImplementedError):
        mgr.get_upgrade_command()


def test_deno_search_maps_jsr_packages(scripted_exec):
    scripted_exec.add("api.jsr.io/packages?query=http", stdout=json.dumps({"items": [
        {"scope": "std", "name": "http", "description": "HTTP utils", "latestVersion": "1.0.2"},
        {"scope": "x", "name": "y"},
    ]}))
    results = asyncio.run(DenoManager().search_packages("http"))
    assert results[0] == {"name": "@std/http", "id": "jsr:@std/http", "description": "HTTP utils", "version": "1.0.2"}
    assert results[1]["description"] == "" and results[1]["version"] == ""
