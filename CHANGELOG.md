# Changelog

All notable changes to PolyGet will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.1.0] - 2026-11-16

### Added
- **Model Context Protocol (MCP) Server**: Native stdio MCP server (`app/mcp_server.py`) exposing 9 schema-validated tools for AI agents (`agy`, Claude Code, Cursor).
- **CLI Subcommand**: Added `polyget mcp` / `python run.py mcp` to launch the MCP daemon directly from the unified entry point.
- **Showcase Documentation & Assets**: Direction C Quad-Console Telemetry Deck visual assets (`docs/assets/banner.svg`, `divider.svg`, `mcp-flow.svg`, `social-preview.png`).
- **Comprehensive Companion Docs**: Added `docs/mcp-server.md`, `docs/architecture.md`, `docs/guides/adding-a-driver.md`, and `CONTRIBUTING.md`.
- **TUI Software Sources Launcher**: Direct access to `asahi-deck` / `repo-config-deck` from terminal interface.

### Changed
- Promoted PolyGet architecture from tri-interface to quad-interface symmetry (GUI, TUI, CLI, MCP).
- Updated `requirements.txt` to include `mcp>=2.0.0`.
- Backported concurrency locks in `coordinator`, `history_store`, `settings_store`, and `ignore_store`.
- Hardened `pacman` driver against partial upgrades (`-Sy <pkgs>`).
- Hardened CI runner against distro-dependent package manager assumptions in `test_mcp_server.py`.
- Improved TUI keyboard interrupt handling during Control Deck suspension.

---

## [1.0.0] - 2026-10-17

### Added
- PySide6 desktop graphical interface with visual semver bump indicators (`+major`, `+minor`, `+patch`).
- Textual TUI (`python run.py --tui`) for headless and SSH workflows with polkit-aware sudo fallback.
- Headless JSON CLI (`python run.py <command> --json`) with strict exit code contracts (`0` OK, `1` manager failure, `2` usage error).
- Multi-distro package manager support across 31 active backends (DNF, Pacman, Flatpak, Cargo, NPM, Pipx, uv, Bun, etc.).
- Cross-manager version collision detection (`polyget newest`).
- Security vulnerability audit engine (`polyget audit`).
- Pre/post transactional lifecycle hooks (`polyget hooks`).
- Dual-machine development workflow hardening (CachyOS x86_64 and Fedora Asahi Remix aarch64).
