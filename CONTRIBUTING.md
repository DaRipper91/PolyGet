# Contributing to PolyGet

PolyGet is developed on two physical Linux environments (Fedora Asahi Remix on Apple Silicon M1 and CachyOS Arch x86_64) feeding one unified `master` line.

---

## ✦ Development Environment Setup

1. Clone and enter the repository:
   ```bash
   git clone https://github.com/DaRipper91/PolyGet.git
   cd PolyGet
   ```
2. Create and activate a Python 3.10+ virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   ```

---

## ❖ Multi-Machine Branching Rules

Read [`BRANCHING.md`](BRANCHING.md) before pushing or promoting code:
- **`master`** is co-owned and contains only code verified on both Asahi and CachyOS.
- **`Asahi/BETA-FEATURES`** is written exclusively from the Asahi laptop.
- **`CachyOS/BETA-FEATURES`** is written exclusively from the CachyOS desktop.
- Never force-push to `master` or beta branches.

---

## ✦ Testing Mandate

All tests must run without requiring physical hardware displays or external package repositories:

```bash
# Run complete test suite headlessly
QT_QPA_PLATFORM=offscreen pytest

# Run a focused test module
QT_QPA_PLATFORM=offscreen pytest tests/test_mcp_server.py
```

---

## ❖ Code Style Invariants

- **Zero `shell=True`**: Never assemble shell command strings. All subprocesses run via `asyncio.create_subprocess_exec` with explicit `argv` lists.
- **Distro logic**: Always route distribution-specific logic through [`app/core/distro.py`](app/core/distro.py).
- **Single Source of Truth**: The root [`AGENTS.md`](AGENTS.md) is the canonical instructions file; `CLAUDE.md`, `GEMINI.md`, and `.cursorrules` are symlinks pointing directly to it.
