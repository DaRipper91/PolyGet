# Model Context Protocol (MCP) Server

PolyGet provides a native Model Context Protocol (MCP) server daemon over `stdio`, exposing cross-manager inspection, search, vulnerability audits, and dry-run upgrade planning as first-class, schema-validated tools for autonomous AI agents such as **Antigravity (`agy`)**, **Claude Code**, and **Cursor**.

---

## ✦ Connecting PolyGet to AI Agents

### 1. Antigravity CLI (`agy`)
Register PolyGet directly via `agy mcp add`:

```bash
agy mcp add polyget /path/to/PolyGet/.venv/bin/python /path/to/PolyGet/mcp_server.py
```

Verify active registration:
```bash
agy mcp list
# Output:
# NAME     TYPE   STATUS   COMMAND/URL
# polyget  stdio  enabled  /path/to/PolyGet/.venv/bin/python /path/to/PolyGet/mcp_server.py
```

### 2. Claude Code (`~/.claude.json` or project config)
Add the stdio server definition to your `mcpServers` block:

```json
{
  "mcpServers": {
    "polyget": {
      "command": "/path/to/PolyGet/.venv/bin/python",
      "args": ["/path/to/PolyGet/mcp_server.py"]
    }
  }
}
```

### 3. Cursor (`~/.cursor/mcp.json`)
Configure an stdio MCP client in Cursor:

```json
{
  "mcpServers": {
    "polyget": {
      "command": "/path/to/PolyGet/.venv/bin/python",
      "args": ["/path/to/PolyGet/run.py", "mcp"]
    }
  }
}
```

---

## ❖ Tool Inventory

All 9 tools execute through PolyGet's asynchronous driver registry ([`app/core/manager.py`](file:///home/daripper/Projects/PolyGet/app/core/manager.py)) and maintain the strict invariant contract: **no `shell=True`**, **zero destructive side-effects on inspection**, and **plan-mode default for mutating operations**.

| Tool Name | Parameters | Return Type | Description |
|---|---|---|---|
| `polyget_list_managers` | `all: bool = False` | `list[dict]` | Enumerates all detected (or cataloged) package managers, category, availability, and repo support. |
| `polyget_check_outdated` | `manager: str?`, `include_ignored: bool` | `dict` | Returns lists of pending updates across drivers with current vs new version strings and manager health statuses. |
| `polyget_list_installed` | `manager: str?` | `dict` | Lists all installed software packages recognized by the target driver or all active drivers. |
| `polyget_search` | `query: str`, `manager: str?`, `limit: int` | `dict` | Searches package registries concurrently. Errors on broken registries are isolated without dropping valid results. |
| `polyget_audit` | `manager: str?` | `dict` | Runs CVE and security vulnerability checks across supporting backends (`npm audit`, `cargo audit`, `pip-audit`). |
| `polyget_list_repos` | `manager: str?` | `list[dict]` | Returns configured mirrors, PPAs, COPRs, and remotes for managers supporting them (DNF, Flatpak, APT). |
| `polyget_needs_restart` | *none* | `dict` | Checks whether recently applied system package updates (e.g. systemd, glibc, kernel) require a daemon restart or system reboot. |
| `polyget_upgrade_plan` | `manager: str?`, `packages: list[str]?` | `dict` | Generates a dry-run execution plan showing the exact subprocess `argv` command lines and transactional hooks that would run. |
| `polyget_history` | `limit: int = 10` | `list[dict]` | Fetches recent upgrade, install, and removal transaction logs recorded by PolyGet. |

---

## ✦ Execution Flow & Invariants

```
Agent Prompt ("What's outdated on this system?")
       │
       ▼
stdio JSON-RPC [tools/call: polyget_check_outdated]
       │
       ▼
app/mcp_server.py (MCPServer 2.x Router)
       │
       ▼
app/core/manager.py (discover_managers())
       │
   ┌───┴───────────────────────────────┐
   │ Concurrently queries 31 drivers:  │
   │  • DNF (RPM-OSTree / Polkit)      │
   │  • Flatpak (Universal)            │
   │  • Cargo, NPM, Pipx, uv (Dev)     │
   └───┬───────────────────────────────┘
       │
       ▼
Structured JSON Return ({ updates: [...], managers: { ... } })
```

* **Zero Shell Injection**: The MCP server maps directly to Python driver calls using typed parameter dictionaries. No shell strings are ever assembled.
* **Elevation Isolation**: Mutating operations cannot run directly without plan generation. An agent must first invoke `polyget_upgrade_plan` to inspect the exact `argv` vector before executing.
