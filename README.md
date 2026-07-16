# ❖ PolyGet

> *One store to rule every package manager.*

Your system runs Pacman. Your other system runs DNF. Flatpak doesn't care which. Neither does npm,
Cargo, Pipx, or RubyGems. PolyGet doesn't care either — it's a PySide6 desktop app (with a Textual
TUI riding shotgun) that gives all of them one dashboard, one search bar, and one place to manage
repos and remotes. 15 drivers, one interface, zero "wait, which package manager owns this again?"

Forged across two daily-driver machines that don't agree on anything by default: CachyOS
(Arch-based) and Asahi Linux (Fedora-based) — which is exactly why the Pacman driver and the DNF
driver both get held to the same standard, not just whichever one the author happened to be
staring at that day.

---

## Project structure

- `run.py` — GUI entry point
- `requirements.txt` — the usual suspects
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

---

## ❖ Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

---

## Development with Claude Code

`CLAUDE.md` covers the design principles above in more depth, the previously-confirmed driver bugs
worth double-checking haven't crept back in, and this repo's cloud-environment quirks.

A `rip-it-apart` audit skill lives under `.claude/skills/` and `.claude/agents/` — six subagents
run in sequence (recon → verify → hunt bugs → find strengths → critique → write the fix plan) for
an honest, cited teardown whenever you want one.

A cloud environment is configured for Claude Code on the web — Ubuntu-based, with Flatpak, Pipx,
and headless Qt6 (`QT_QPA_PLATFORM=offscreen`) ready for driver and UI work. **Reality check:** no
Pacman, no DNF, up there — those two only exist on real Arch and Fedora hardware, which is to say,
exactly where this project was always meant to be tested anyway.

---

## License

MIT — see `LICENSE`.

---

❖
