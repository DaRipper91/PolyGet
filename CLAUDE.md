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
python run.py
```

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

- `run.py` — entry point launcher
- `requirements.txt` — Python package requirements
- `app/core/` — reusable package manager drivers and base class (adapted from `upgrader-tui`)
- `app/ui/` — PySide6 window layouts, styling, and thread workers
- `docs/plans/` — dated design docs and implementation plans; check here first for the *why*
  behind a feature before re-deriving it from the diff
- `tests/` — test suite

## Known, previously-confirmed bugs (check these haven't regressed)

- **Flatpak driver**: the `-j` flag is broken in the underlying `flatpak` CLI invocation.
- **Pipx driver**: does a fake PyPI lookup — reports success without actually checking PyPI.
- **Pacman driver**: uses an inverted exit-code convention relative to the other drivers, which
  can cause success/failure to be reported backwards if not specifically handled.

These were confirmed real during a prior code review, with Antigravity implementation plans
written for each — check `docs/plans/` for the corresponding fix-plan documents before assuming
these are still open or already fixed.

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
