# FILE_GUIDE.md — Repository Config Deck Bundles

## 🍎 Asahi Bundle (Fedora Asahi Remix, M1 MacBook Air)

| File | Goes where | What it does | Placeholders |
|---|---|---|---|
| `configure-dnf.sh` | Run from repo root | Walks `dnf.conf` options and repo cards. Stages, diffs, and dry-runs before apply. | none |
| `asahi-deck.py` | Run from repo root | Curses TUI for dnf.conf options and `repos.catalog`. Category filtering, diffs, live build checks, dry-run gate. | none |
| `dnf.conf` | Template; installs to `/etc/dnf/dnf.conf` | Performance, safety, and candy colors for dnf5. | none |
| `repos.catalog` | Next to scripts | Repositories for Fedora Asahi Remix (aarch64). | `{SUDO}`, `{FEDORA}` |
| `DNF-GUIDE.md` | Reference guide | Detailed options and safety rules for Apple Silicon. | none |
| `AGENT_BRIEF.md` | Agent directives | Guardrails and instructions for AI collaborators. | none |

## 📱 Pixel 10 Pro Bundle (Termux / Android 17 / Tensor G5)

| File | Goes where | What it does | Placeholders |
|---|---|---|---|
| `configure-apt.sh` | Run from repo root | Interactive & headless CLI for Termux `apt` and repository sources. Dry-run gated. | none |
| `pixel-deck.py` | Run from repo root (or `termux-deck.py`) | Native curses TUI for Google Pixel 10 Pro. Walks `apt.conf` options, repository cards, search, and diff review. | none |
| `apt.conf` | Installs to `$PREFIX/etc/apt/apt.conf.d/99pixel-deck` | Mobile latency, storage saving (`Clean-Installed`), memory ceiling protection, and Zero-Trust safety. | none |
| `termux-repos.catalog` | Next to scripts | Catalog of Termux apt repositories, TUR, root-required tools, and refused repos. | `{PREFIX}` |
| `APT-GUIDE.md` | Reference guide | Comprehensive guide to Android 17 / Termux package configuration. | none |
| `PIXEL_BRIEF.md` | Agent directives | Hardware specifications, memory constraints, and safety policies for da-pixel-10-pro. | none |
| `pixel-deck.desktop` | Launcher / App shortcut | Desktop launcher definition for X11/Wayland sessions. | none |
| `pixel-deck.svg` | Icon asset | Scalable icon featuring Pixel visor, Tensor G5 chip, and verification badge. | none |

## ⚙️ Shared Libraries

| File | Goes where | What it does |
|---|---|---|
| `lib/walk.sh` | `lib/` | Shared walk engine (options walk, repo cards, guardrails) across dnf and apt. |
| `lib/dryrun-gate.sh` | `lib/` | Shared dry-run gate enforcing zero-trust preflight checks prior to apply. |
