<div align="center">

# ❖ PolyGet

### *One store to rule every package manager.*

[![License: MIT](https://img.shields.io/badge/license-MIT-blueviolet.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-41cd52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![Textual](https://img.shields.io/badge/TUI-Textual-a970ff)](https://textual.textualize.io/)
[![Drivers](https://img.shields.io/badge/drivers-15%20active%20%2F%2032%20cataloged-orange)](#-supported-package-managers)
[![Subprocess safety](https://img.shields.io/badge/shell%3DTrue-never-critical.svg)](#-design-principles-the-load-bearing-ones)
[![Platform](https://img.shields.io/badge/tested%20on-Arch%20%7C%20Fedora-informational)](#-development-with-claude-code)

</div>

---

Your system runs Pacman. Your other system runs DNF. Flatpak doesn't care which. Neither does npm,
Cargo, Pipx, RubyGems, or the other ten Language/Dev tools piling up in your `~/.local`. PolyGet
doesn't care either — it's a PySide6 desktop app (with a Textual TUI riding shotgun) that gives all
of them one dashboard, one search bar, and one place to manage repos and remotes. **15 drivers, one
interface, zero "wait, which package manager owns this again?"**

Forged across two daily-driver machines that don't agree on anything by default: CachyOS
(Arch-based) and Asahi Linux (Fedora-based) — which is exactly why the Pacman driver and the DNF
driver both get held to the same standard, not just whichever one the author happened to be
staring at that day.

<div align="center">

**[Features](#-features) · [Supported managers](#-supported-package-managers) · [Setup](#-setup) ·
[Structure](#project-structure) · [Design principles](#-design-principles-the-load-bearing-ones) ·
[Claude Code](#-development-with-claude-code)**

</div>

---

## ✦ Features

- **Unified dashboard** — every outdated package across every active manager, in one scrollable
  list, with per-manager scan status and failure surfacing (a failed scan shows up as *failed*,
  never silently as "up to date").
- **Batch upgrades** — select what you want, hit go, watch a live console; failures are collected
  and reported per-manager instead of a blanket "done!" that may not be true.
- **Manager Store** — search and install *new* software across every driven backend, plus browse
  AppStream categories (Development, Games, Graphics, and friends) blending Flatpak and DNF results.
- **Manager catalog** — the store also shows package managers you don't have installed yet (Zypper,
  Nix, Snap, Guix, Composer, Maven, and more) with one-click, distro-aware self-install commands.
  Seeing what you *could* have is a feature, not scope creep.
- **Repository management** — list, add, enable/disable, and remove repos/remotes for every backend
  that supports the concept (DNF, APT, Flatpak), from inside the app.
- **Blueprints** — export your installed-package state to a portable YAML file, diff it against a
  fresh machine, and sync the drift in either direction. Version-pinning included.
- **Textual TUI** — the same driver layer, in your terminal, for headless boxes and SSH sessions
  (`python run.py --tui`). Includes a polkit-aware sudo fallback for sessions with no auth agent.
- **Scriptable CLI** — `python run.py outdated --json` and friends: the same driver layer with no
  GUI, one JSON document per call, meaningful exit codes, and dry-run-by-default for anything that
  changes the system. Built for shell scripts, cron jobs, and AI coding agents alike.

---

## ✦ Supported package managers

15 drivers actively query and act on your system today; the catalog tracks 32 managers total so the
Store can point at the other 17 even before a driver exists for them.

| Category | Driven today | Catalog-only (browsable, self-installable) |
|---|---|---|
| **System** | DNF · Pacman · APT | Paru · Zypper · APK · XBPS · Portage · eopkg |
| **Universal** | Flatpak | Nix · Snap · Distrobox · Guix |
| **Language/Dev** | NPM · Pipx · Cargo · RubyGems · Yarn · pnpm · Dart Pub · Hex · cpanm · Poetry · Julia | Composer · Go Modules · NuGet · Maven · LuaRocks · Bundler · Gradle |

Want one of the catalog-only entries driven? `app/core/drivers/` is where a new one goes — the
registry auto-discovers anything dropped in there and decorated with `@register_manager`.

---

## Project structure

- `run.py` — entry point (`python run.py` for the GUI, `python run.py --tui` for the terminal UI)
- `requirements.txt` — the usual suspects, pinned to what this codebase is actually tested against
- `app/core/` — the drivers and the shared base class they all answer to
- `app/ui/` — PySide6 windows, styling, thread workers, and the TUI
- `docs/plans/` — dated design docs; read these before re-deriving the *why* from a diff
- `tests/` — the suite that keeps this honest
- `ROADMAP.md` — what's shipped and what's planned next

---

## ❖ Design principles (the load-bearing ones)

- **No `shell=True`. Ever.** Every subprocess call uses `asyncio.create_subprocess_exec` with
  argument lists. Not a preference — the thing standing between "package search" and "arbitrary
  shell injection."
- **Distro-awareness has exactly one home.** `app/core/distro.py`. Anything that branches on
  distro family anywhere else is a bug wearing a "just this once" disguise.
- **The catalog shows what you *could* install**, not just what's already there.
  `app/core/catalog.py` exists so the Manager Store doesn't just describe your system back to you.
- **Silent success is worse than a loud failure.** A hung or failed check surfaces as an error in
  the UI — it never gets quietly reported as "up to date" just because an exception happened to be
  caught somewhere.

---

## ✦ Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py         # PySide6 GUI
python run.py --tui   # Textual TUI, for terminal-only / headless sessions
```

### Command line

Any subcommand skips the GUI entirely. Add `--json` for machine-readable output (stdout is a
single JSON document; progress goes to stderr).

```bash
python run.py managers                  # which package managers are on this machine
python run.py outdated                  # every pending update, grouped by manager
python run.py outdated -m npm --json    # one manager, as JSON
python run.py search ripgrep            # search every backend at once
python run.py audit                     # known vulnerabilities (npm audit, cargo audit, ...)
python run.py upgrade -m flatpak        # print the upgrade plan...
python run.py upgrade -m flatpak --yes  # ...and actually run it
python run.py install -m dnf htop --yes
python run.py ignore add npm some-pkg   # never auto-upgrade this one
python run.py history                   # what got upgraded, when, and whether it worked
```

`upgrade`, `install`, and `sync` only print the exact commands they would run until you pass
`--yes`. Exit codes: `0` ok, `1` a manager or command failed, `2` usage error.

Running the test suite:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

---

## ❖ Development with Claude Code

`CLAUDE.md` covers the design principles above in more depth, the previously-confirmed driver bugs
worth double-checking haven't crept back in, and this repo's cloud-environment quirks.

Claude Code can drive PolyGet directly. The `polyget` skill (`.claude/skills/polyget/`) teaches
it the CLI: questions like "what's outdated?" or "which manager has ripgrep?" get answered with
`run.py ... --json`, and upgrades are shown as a plan for you to approve, never run on their own.
`.claude/settings.json` pre-approves the read-only subcommands and the test suite so those don't
trigger permission prompts.

A `rip-it-apart` audit skill lives under `.claude/skills/` and `.claude/agents/` — six subagents
run in sequence (recon → verify → hunt bugs → find strengths → critique → write the fix plan) for
an honest, cited teardown whenever you want one, plus an optional seventh stage for wide-ranging
feature-expansion brainstorming.

A cloud environment is configured for Claude Code on the web — Ubuntu-based, with Flatpak, Pipx,
and headless Qt6 (`QT_QPA_PLATFORM=offscreen`) ready for driver and UI work. **Reality check:** no
Pacman, no DNF, up there — those two only exist on real Arch and Fedora hardware, which is to say,
exactly where this project was always meant to be tested anyway.

---

## License

MIT — see `LICENSE`.

<div align="center">

❖

</div>
