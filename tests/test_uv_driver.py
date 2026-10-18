import asyncio

import pytest

from app.core.drivers.uv import UvManager, _is_newer
from app.core.manager import DriverError

TOOL_LIST = "hcom v0.7.25\n- hcom\naider-chat v0.86.2\n- aider\n"


def test_installed_versions_skip_executable_rows(scripted_exec):
    scripted_exec.add("uv tool list", stdout=TOOL_LIST)
    assert asyncio.run(UvManager().list_installed_versions()) == {"hcom": "0.7.25", "aider-chat": "0.86.2"}


def test_check_updates_only_reports_newer(scripted_exec):
    scripted_exec.add("uv tool list", stdout=TOOL_LIST)
    scripted_exec.add("pypi.org/pypi/hcom/json", stdout='{"info": {"version": "0.7.30"}}')
    scripted_exec.add("pypi.org/pypi/aider-chat/json", stdout='{"info": {"version": "0.86.2"}}')
    assert asyncio.run(UvManager().check_updates()) == [{"name": "hcom", "current": "0.7.25", "new": "0.7.30"}]


def test_check_updates_partial_lookup_failure_keeps_other_results(scripted_exec):
    scripted_exec.add("uv tool list", stdout=TOOL_LIST)
    scripted_exec.add("pypi.org/pypi/hcom/json", stdout='{"info": {"version": "0.7.30"}}')
    scripted_exec.add("pypi.org/pypi/aider-chat/json", rc=22, stderr="curl: (22) 404")
    assert [u["name"] for u in asyncio.run(UvManager().check_updates())] == ["hcom"]


def test_check_updates_total_registry_failure_raises(scripted_exec):
    scripted_exec.add("uv tool list", stdout=TOOL_LIST)
    scripted_exec.add("curl", rc=7, stderr="could not connect")
    with pytest.raises(DriverError):
        asyncio.run(UvManager().check_updates())


def test_no_tools_means_no_updates_and_no_network(scripted_exec):
    scripted_exec.add("uv tool list", stdout="No tools installed\n")
    assert asyncio.run(UvManager().check_updates()) == []


def test_is_newer_handles_unparseable_versions():
    assert _is_newer("1.10.0", "1.9.0")
    assert not _is_newer("1.0.0", "1.0.0")
    assert _is_newer("weird-2", "weird-1")


def test_commands_and_unsupported_search():
    mgr = UvManager()
    assert mgr.get_upgrade_command() == ["uv", "tool", "upgrade", "--all"]
    assert mgr.get_upgrade_command(["hcom"]) == ["uv", "tool", "upgrade", "hcom"]
    assert mgr.get_install_command("ruff") == ["uv", "tool", "install", "ruff"]
    with pytest.raises(NotImplementedError):
        asyncio.run(mgr.search_packages("x"))


# --- tools installed from a local or VCS source must not be compared against an unrelated PyPI project ---

from app.core.drivers import uv as uv_mod

EDITABLE = '[tool]\nrequirements = [{ name = "agentdeck", extras = ["web", "qt"], editable = "/home/u/Projects/agentdeck" }]\nentrypoints = [{ name = "agentdeck", install-path = "/home/u/.local/bin/agentdeck" }]\n'
DIRECTORY = '[tool]\nrequirements = [{ name = "aether", directory = "/home/u/Projects/Aether" }]\n'
GIT = '[tool]\nrequirements = [{ name = "x", git = "https://example.com/x.git" }]\n'
URL = '[tool]\nrequirements = [{ name = "x", url = "https://example.com/x.whl" }]\n'
PATH_SRC = '[tool]\nrequirements = [{ name = "x", path = "/home/u/dist/x.whl" }]\n'
PYPI = '[tool]\nrequirements = [{ name = "hcom" }]\nentrypoints = [{ name = "hcom", install-path = "/home/u/.local/bin/hcom" }]\n'
MULTILINE_PYPI = '[tool]\nrequirements = [\n    { name = "aider-chat", specifier = ">=0.86" },\n    { name = "extra" },\n]\nentrypoints = [{ name = "aider", install-path = "/home/u/.local/bin/aider" }]\n'
MULTILINE_LOCAL = '[tool]\nrequirements = [\n    { name = "a" },\n    { name = "b", editable = "/home/u/b" },\n]\n'


@pytest.mark.parametrize("receipt,expected", [
    (EDITABLE, True), (DIRECTORY, True), (GIT, True), (URL, True), (PATH_SRC, True), (MULTILINE_LOCAL, True),
    (PYPI, False),            # install-path in entrypoints must not look like a `path` source
    (MULTILINE_PYPI, False),
])
@pytest.mark.parametrize("use_tomllib", [True, False], ids=["tomllib", "fallback-py310"])
def test_local_source_detection_matches_with_and_without_tomllib(receipt, expected, use_tomllib, monkeypatch):
    if not use_tomllib:
        monkeypatch.setattr(uv_mod, "tomllib", None)
    elif uv_mod.tomllib is None:
        pytest.skip("this Python has no tomllib")
    assert uv_mod._has_local_source(receipt) is expected


def test_malformed_receipt_is_not_treated_as_local():
    assert uv_mod._has_local_source("[tool\nrequirements = broken") is False


def _tool_dir(tmp_path, receipts):
    for tool, text in receipts.items():
        (tmp_path / tool).mkdir()
        if text is not None:
            (tmp_path / tool / "uv-receipt.toml").write_text(text)
    return tmp_path


def test_local_source_tools_never_get_a_pypi_lookup_and_are_not_reported(scripted_exec, tmp_path):
    root = _tool_dir(tmp_path, {"aether": DIRECTORY, "hcom": PYPI})
    scripted_exec.add("uv tool list", stdout="aether v0.1.0\n- aether\nhcom v0.7.25\n- hcom\n")
    scripted_exec.add("uv tool dir", stdout=f"{root}\n")
    scripted_exec.add("pypi.org/pypi/hcom/json", stdout='{"info": {"version": "0.7.30"}}')
    # an unrelated PyPI project named "aether" exists; if it were looked up it would look 'outdated'
    scripted_exec.add("pypi.org/pypi/aether/json", stdout='{"info": {"version": "0.3.37"}}')
    assert asyncio.run(UvManager().check_updates()) == [{"name": "hcom", "current": "0.7.25", "new": "0.7.30"}]
    assert not any("pypi.org/pypi/aether" in " ".join(c[0]) for c in scripted_exec.calls)


def test_only_local_tools_means_no_updates_and_no_network(scripted_exec, tmp_path):
    root = _tool_dir(tmp_path, {"aether": DIRECTORY})
    scripted_exec.add("uv tool list", stdout="aether v0.1.0\n- aether\n")
    scripted_exec.add("uv tool dir", stdout=f"{root}\n")
    assert asyncio.run(UvManager().check_updates()) == []
    assert not any("curl" in c[0][0] for c in scripted_exec.calls)


def test_unreadable_receipt_keeps_the_old_pypi_check_instead_of_hiding_the_tool(scripted_exec, tmp_path):
    root = _tool_dir(tmp_path, {"hcom": None})   # directory exists, receipt file does not
    scripted_exec.add("uv tool list", stdout="hcom v0.7.25\n- hcom\n")
    scripted_exec.add("uv tool dir", stdout=f"{root}\n")
    scripted_exec.add("pypi.org/pypi/hcom/json", stdout='{"info": {"version": "0.7.30"}}')
    assert [u["name"] for u in asyncio.run(UvManager().check_updates())] == ["hcom"]


def test_failure_to_locate_the_tool_dir_does_not_break_the_update_check(scripted_exec):
    scripted_exec.add("uv tool list", stdout="hcom v0.7.25\n- hcom\n")
    scripted_exec.add("uv tool dir", rc=2, stderr="boom")
    scripted_exec.add("pypi.org/pypi/hcom/json", stdout='{"info": {"version": "0.7.30"}}')
    assert [u["name"] for u in asyncio.run(UvManager().check_updates())] == ["hcom"]


def test_uv_cleanup_targets(scripted_exec, tmp_path):
    cache_dir = tmp_path / "uv_cache"
    cache_dir.mkdir()
    (cache_dir / "foo").write_bytes(b"x" * 1024)
    scripted_exec.add("uv cache dir", stdout=f"{cache_dir}\n")
    targets = asyncio.run(UvManager().get_cleanup_targets())
    assert len(targets) == 1
    assert targets[0]["command"] == ["uv", "cache", "prune"]
    assert targets[0]["id"] == "cache"
    assert targets[0]["bytes"] == 1024
