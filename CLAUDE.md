# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this repo is

PolyGet is a PySide6 desktop application that unifies package management across every backend
installed on a Linux system — system-level (DNF, Pacman), universal/sandboxed (Flatpak), and
language/dev (NPM, Cargo, Pipx, RubyGems). It presents one dashboard for outdated packages, one
searchable store for installing new software, and one interface for managing repositories/remotes,
regardless of which underlying tool actually owns a given package.

## Running things

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py                 # GUI
python run.py --tui           # Textual TUI
python run.py <command>       # headless CLI (see below)
```

Tests: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q` (whole suite runs in a
few seconds; focus with `tests/test_<area>.py` while iterating).

## Headless CLI (`app/cli.py`) — use this to inspect the real system

`python run.py <command> [--json]` (or just `polyget <command>` — a fish function wraps `run.py`)
drives the same driver layer as the GUI, with no Qt import. Prefer it over ad-hoc
`python -c "import asyncio; ..."` snippets when you need to see what a driver actually returns.

- Read-only: `managers [--all]`, `outdated`, `installed`, `search QUERY`, `audit`, `repos`,
  `history`, `catalog`, `ignore list`. All accept `-m/--manager NAME` (repeatable,
  case-insensitive).
- Mutating: `upgrade`, `install`, `sync` **only print the planned commands** unless `--yes` is
  passed. Never pass `--yes` on your own initiative; show the plan and let the user run it.
  System managers (DNF/Pacman/APT) use `pkexec`, which fails without a TTY/polkit agent, so the
  user should run those themselves via `! polyget upgrade -m dnf --yes`.
- `--json` prints exactly one JSON document on stdout; progress and child-process output go to
  stderr. Exit codes: 0 ok, 1 a manager/command failed (partial results are still printed),
  2 usage error (unknown/uninstalled manager, bad args).
- New subcommands go in `app/cli.py` (add to `COMMANDS` so `app/main.py` routes to it) with a
  test in `tests/test_cli.py`, which swaps in fake managers — never hit real package managers
  in tests.

## Design principles that shape every decision in this codebase

- **No `shell=True`, ever.** Every subprocess call uses `asyncio.create_subprocess_exec` with
  argument lists. This is a hard rule, not a style preference — it's what keeps arbitrary package
  names/queries from becoming a shell-injection vector. Treat any `shell=True` or string-built
  command as a Critical bug, not a stylistic nitpick.
- **Distro-awareness is load-bearing, not optional.** This project runs across a Fedora-based
  machine (Asahi Linux) and an Arch-based machine (CachyOS) as its actual daily-driver test
  environments. Any command that differs by distro family goes through `app/core/distro.py` — it
  is never hardcoded elsewhere, even if the hardcoded version happens to work on whichever machine
  it was written on.
- **A manager you don't have installed should still be visible.** The catalog (`app/core/
  catalog.py`) exists specifically so the Manager Store can show you managers you *could* install,
  not just ones already present. A change that narrows this to "installed managers only" is a
  regression against the actual design intent, not a neutral simplification.

## Project structure

- `run.py` — entry point launcher; `app/main.py` routes to GUI, `--tui`, or the CLI
- `app/cli.py` — headless argparse CLI with `--json` output
- `requirements.txt` — Python package requirements
- `app/core/` — reusable package manager drivers and base class (adapted from `upgrader-tui`)
- `app/ui/` — PySide6 window layouts, styling, thread workers, and the Textual TUI (`tui.py`)
- `app/core/sudo_secret.py` — optional sudo password in the OS keyring (Secret Service/KWallet); TUI only, never written to disk by PolyGet
- `app/core/history_store.py` / `ignore_store.py` — upgrade log (`~/.local/share/polyget/
  history.jsonl`) and ignore list (`~/.config/polyget/ignored_packages.json`), shared by GUI and CLI
- `docs/plans/` — dated design docs and implementation plans; check here first for the *why*
  behind a feature before re-deriving it from the diff
- `tests/` — test suite

## Previously-fixed bugs (check these haven't regressed)

- **Flatpak driver**: used a `-j` flag the `flatpak` CLI doesn't support; now uses `--json`.
- **Pipx driver**: used to fake its PyPI lookup; now queries PyPI's simple index and JSON API.
- **Pacman driver**: `pacman -Qu` exits 1 when there are simply no updates; treating that as a
  failure (or the reverse) flips success/failure reporting.

Fix plans for each live in `docs/plans/`.

## Cloud environment limitations

This repo's Claude Code cloud environment runs on a fixed Ubuntu base — it cannot run `pacman` or
`dnf` natively, since those are Arch/Fedora-specific package managers with no Ubuntu equivalent.
Driver-level testing for Pacman and DNF happens locally on the real CachyOS (Arch) and Asahi
(Fedora) machines instead. The cloud environment covers Flatpak, Pipx, npm/cargo/gem driver work,
and UI/catalog logic (PySide6 running headless via `QT_QPA_PLATFORM=offscreen`).

## Before creating a PR or session

Same policy as this developer's other repos: before creating a new PR or session for a task, check
whether one already exists for the same scope (open PRs, active sessions) rather than assuming a
clean slate. If one exists and looks stale, say so and ask before creating a parallel one.
