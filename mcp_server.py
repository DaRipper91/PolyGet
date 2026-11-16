#!/usr/bin/env python3
"""Entry point for the PolyGet Model Context Protocol (MCP) server."""

import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.mcp_server import run_server

if __name__ == "__main__":
    run_server()
