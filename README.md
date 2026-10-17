<div align="center">

# ❖ PolyGet

### *One store to rule every package manager.*

[![License: MIT](https://img.shields.io/badge/license-MIT-blueviolet.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-41cd52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![Textual](https://img.shields.io/badge/TUI-Textual-a970ff)](https://textual.textualize.io/)
[![Drivers](https://img.shields.io/badge/drivers-27%20active%20%2F%2037%20cataloged-orange)](#-supported-package-managers)
[![shell=True never](https://img.shields.io/badge/shell%3DTrue-never-critical.svg)](#-design-principles)
[![Platform](https://img.shields.io/badge/tested%20on-Arch%20%7C%20Fedora-informational)](#-development-with-claude-code)
[![Tests](https://img.shields.io/badge/tests-402%20passing-brightgreen)](#-testing)

</div>

---

Your system runs Pacman. Your other system runs DNF. Flatpak doesn't care which. Neither does npm,
Cargo, Pipx, RubyGems, or the other twenty-plus Language/Dev tools piling up in your `~/.local`.
PolyGet doesn't care either — it's a **PySide6 desktop app** (with a **Textual TUI** riding shotgun)
that gives all of them one dashboard, one search bar, and one place to manage repos and remotes.
**27 drivers, one interface, zero "wait, which package manager owns this again?"**

Forged across two daily-driver machines that don't agree on anything by default: **CachyOS**
(Arch-based) and **Asahi Linux** (Fedora-based) — which is exactly why the Pacman driver and the DNF
driver both get held to the same standard.

<div align="center">

**[Features](#-features) · [Shortcuts](#-keyboard-shortcuts) [Supported managers](#-supported-package-managers) · [Setup](#-setup) · [CLI](#-command-line) · [Design](#-design-principles) · [Claude Code](#-development-with-claude-code)**

</div>

---

## ✦ Features

| | |
|---|---|
| **📦 Unified dashboard** | Every outdated package across every active manager, grouped under a header per manager with its scan status. A failed scan shows up as *failed* — never silently as "up to date" — with a **Retry** for just that manager. |
| **⚡ Batch upgrades** | Select what you want, hit go, watch a live console terminal overlay. Before you press Update, a bar says how many picks will ask for your admin password; **Only user-level** upgrades just the ones that won't. Failures are collected and reported per-manager instead of a blanket "done!" that may not be true. Non-elevated managers (Flatpak, Pipx, npm, ...) upgrade **in parallel**; elevated ones (DNF, Pacman, APT, Snap) run sequentially for sudo auth. |
| **🏪 Manager Store** | Search and install *new* software across every driven backend, plus browse AppStream categories (Development, Games, Graphics, and friends) blending Flatpak with your distro's own packages (DNF, Pacman, or APT). Installs always go through the owning driver. An **Installed** view lists what you have, and **Remove…** (also in each update's ⋯ menu) previews every package that would go with it before anything runs. |
| **📋 Manager catalog** | The store also shows package managers you don't have installed yet (Zypper, Nix, Snap, Composer, Maven, and more) with one-click, distro-aware self-install commands. Seeing what you *could* have is a feature, not scope creep. |
| **🔧 Repository management** | List, add, enable/disable, and remove repos/remotes for every backend that supports the concept (DNF, APT, Flatpak), from inside the app. |
| **📐 Blueprints** | Export your installed-package state to a portable YAML file, diff it against a fresh machine, and sync the drift in either direction. Version-pinning included. |
| **🖥️ Textual TUI** | The same driver layer, in your terminal, for headless boxes and SSH sessions (`python run.py --tui`). Includes a polkit-aware sudo fallback for sessions with no auth agent. |
| **💻 Scriptable CLI** | `python run.py outdated --json` and friends: the same driver layer with no GUI, one JSON document per call, meaningful exit codes, and dry-run-by-default for anything that changes the system. Built for shell scripts, cron jobs, and AI coding agents alike. |
| **🔍 Self-version** | `python run.py self-version` shows each package manager's own version string — know what's driving your system before you upgrade it. |
| **🪄 GUI tweaks** | Live-adjustable **UI scale** (75–200%) and **font size** (8–32 px). Switchable **sidebar styles**: classic banner, name & system info, or a status card for the header; classic list, grouped sections, or an icon rail for navigation. Keyboard shortcuts (Ctrl+R scan, Ctrl+U upgrade, Ctrl+S sync, F1 Debug Console, Escape hide terminal, Ctrl+Q quit). Dark-themed menus, dropdowns, and tooltips everywhere. |
| **🐞 Debug Console** | A live stream of every package-manager command inside the app, plus a toggle for JSONL file logging so AI coding assistants (Claude Code, Codex, Copilot, OpenCode) can read your debug log without running PolyGet themselves. |
| **🔑 Keyring** | Sudo password stored in your OS keyring (Secret Service / KWallet) so pkexec can fall back to sudo when no polkit agent is bound. Forget it from Settings whenever you want. |

---

## ✦ Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+R` | Check for Updates (scan) |
| `Ctrl+U` | Update Selected (batch upgrade) |
| `Ctrl+S` | Sync Repositories |
| `Ctrl+Shift+U` | Run Version Scan (cross-manager) |
| `F1` | Open Debug Console |
| `Escape` | Hide Terminal Overlay |
| `Ctrl+Q` | Quit PolyGet |

---

## ✦ Supported package managers

27 drivers actively query and act on your system today; the catalog tracks 37 managers total so the
Store can point at the other 10 even before a driver exists for them.

| Category | Driven today | Catalog-only (browsable, self-installable) |
|---|---|---|
| **System** | DNF · Pacman · APT · AUR (paru/yay) | Zypper · APK · XBPS · Portage · eopkg |
| **Universal** | Flatpak · Homebrew (macOS + Linuxbrew) · Snap · Nix · Distrobox | Guix |
| **Language/Dev** | NPM · Pipx · uv · Cargo · Go · RubyGems · Bundler · Gradle · Yarn · pnpm · Bun · Deno · Conda · Dart Pub · Hex · cpanm · Poetry · Julia | Composer · NuGet · Maven · LuaRocks |

Two of those are per-project tools with no global package list. **Bundler** and **Gradle** scan the
directories you register with `python run.py projects add DIR` (a `Gemfile`, or a Gradle wrapper),
and stay hidden until one is registered. Their upgrades act on one project at a time. A few
managers can't report what's outdated (Deno, Nix, Distrobox); the scan shows them as unsupported
rather than "up to date".

Want one of the catalog-only entries driven? `app/core/drivers/` is where a new one goes — the
registry auto-discovers anything dropped in there and decorated with `@register_manager`.

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
python run.py self-version              # each manager's own version string
python run.py search ripgrep            # search every backend at once
python run.py audit                     # known vulnerabilities (npm audit, cargo audit, ...)
python run.py upgrade -m flatpak        # print the upgrade plan...
python run.py upgrade -m flatpak --yes  # ...and actually run it
python run.py install -m dnf htop --yes
python run.py ignore add npm some-pkg   # never auto-upgrade this one
python run.py projects add ~/code/app   # let Bundler/Gradle scan this project
python run.py history                   # what got upgraded, when, and whether it worked
```

`upgrade`, `install`, and `sync` only print the exact commands they would run until you pass
`--yes`. Exit codes: `0` ok, `1` a manager or command failed, `2` usage error.

Running the test suite (the test dependencies, including `pytest-asyncio`, are in `requirements-dev.txt`):

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen pytest
```

---

## ✦ Design principles

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

## ✦ Development with Claude Code

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
