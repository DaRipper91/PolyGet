"""Tests for PolyGet Model Context Protocol (MCP) server."""

import pytest
from app.mcp_server import create_server


@pytest.fixture
def mcp_server():
    return create_server()


@pytest.mark.asyncio
async def test_mcp_server_tool_registration(mcp_server):
    tools = await mcp_server.list_tools()
    names = {t.name for t in tools}
    expected = {
        "polyget_list_managers",
        "polyget_check_outdated",
        "polyget_list_installed",
        "polyget_search",
        "polyget_audit",
        "polyget_list_repos",
        "polyget_needs_restart",
        "polyget_upgrade_plan",
        "polyget_history",
    }
    assert expected.issubset(names)


@pytest.mark.asyncio
async def test_mcp_list_managers_call(mcp_server):
    res = await mcp_server.call_tool("polyget_list_managers", {"all": False})
    assert not res.is_error
    assert "result" in res.structured_content
    managers = res.structured_content["result"]
    assert isinstance(managers, list)
    assert len(managers) > 0
    assert any(m["name"] in ("DNF", "APT", "Pacman", "Flatpak", "Homebrew", "Snap") for m in managers)

    # With all=True, full catalog is returned including DNF regardless of host distro
    res_all = await mcp_server.call_tool("polyget_list_managers", {"all": True})
    assert not res_all.is_error
    catalog = res_all.structured_content["result"]
    assert any(m["name"] == "DNF" for m in catalog)


@pytest.mark.asyncio
async def test_mcp_needs_restart_call(mcp_server):
    res = await mcp_server.call_tool("polyget_needs_restart", {})
    assert not res.is_error
    data = res.structured_content
    assert "needed" in data
    assert "method" in data


@pytest.mark.asyncio
async def test_mcp_upgrade_plan_dry_run(mcp_server):
    res = await mcp_server.call_tool("polyget_upgrade_plan", {})
    assert not res.is_error
    plan = res.structured_content
    assert plan["executed"] is False
    assert "steps" in plan
