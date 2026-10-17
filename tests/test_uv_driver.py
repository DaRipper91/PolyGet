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
