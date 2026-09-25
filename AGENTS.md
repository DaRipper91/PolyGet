# Repository Guidelines

## Project Structure & Module Organization

PolyGet is a Python desktop application that unifies package managers.

- `run.py` launches the application; `requirements.txt` lists runtime dependencies.
- `app/core/` contains manager discovery, distro detection, catalogs, coordination, and
  package-manager drivers under `app/core/drivers/`.
- `app/ui/` contains the PySide6 GUI, Textual TUI, workers, and stylesheets.
- `tests/` contains pytest tests for core logic, drivers, and GUI behavior.
- `app/core/data/manager_catalog.yaml` contains catalog data; `docs/plans/` contains dated
  design and implementation plans. Read relevant plans before changing behavior.

## Build, Test, and Development Commands

Create an isolated environment and run the GUI with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

`python run.py <command> [--json]` is a headless CLI (`app/cli.py`) over the same drivers:
`managers`, `outdated`, `installed`, `search`, `audit`, `repos`, `history`, `catalog`, `ignore`
are read-only; `upgrade`, `install`, `sync` print a plan and only execute with `--yes`. Use it to
check real driver output instead of one-off Python snippets. Exit codes: 0 ok, 1 failure, 2 usage.

Run the full test suite with `QT_QPA_PLATFORM=offscreen pytest`. Use a focused run such as
`QT_QPA_PLATFORM=offscreen pytest tests/test_npm_driver.py` while iterating. The offscreen
setting keeps Qt tests usable in headless environments. Pacman and DNF behavior should also be
verified on their native Arch- and Fedora-based systems when possible.

## Coding Style & Naming Conventions

Use Python 4-space indentation, descriptive `snake_case` functions and variables, and
`PascalCase` classes. Keep driver-specific behavior in its driver module and shared behavior in
the base manager/core modules. Route distro-specific decisions through `app/core/distro.py`.
Use argument lists with `asyncio.create_subprocess_exec`; never use `shell=True` or construct
shell command strings from package names or user queries. No repository-wide formatter or linter
is configured, so keep changes small and consistent with neighboring code.

## Testing Guidelines

Add or update pytest tests alongside behavior changes. Name files `test_<area>.py` and tests
`test_<behavior>`. Mock subprocesses, package-manager availability, network calls, and Qt
workers rather than requiring a specific machine or installed package manager.

## Commit & Pull Request Guidelines

Recent commits use short, imperative summaries, often with `Fix`, `Add`, or `chore:` prefixes
(for example, `Add apt driver for Debian/Ubuntu System-category coverage`). Keep commits focused.
PRs should explain the user-visible change, include tests run and environment limitations, link
the relevant issue or plan when applicable, and include screenshots for GUI changes. Check for an
existing PR or active session covering the same scope before opening a new one.
