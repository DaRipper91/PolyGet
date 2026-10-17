# PolyGet: Feature Roadmap — 2026-10-17

Ideas gathered while the UI redesign is in progress, ordered by how much day-to-day pain each
removes. Each item names the machine it has to be developed on under the branch workflow
(CachyOS beta / Asahi beta → port to the other → stable). "Either" means it can be built and
tested in the Ubuntu cloud environment with fake managers.

## Tier 1 — daily-use gaps

### 1. Uninstall with reverse-dependency preview — **core + CLI done**
- `PackageManager.get_remove_command(packages)` on every driver that can install, except Go
  (loose binaries in `$GOBIN`), Bundler and Gradle (per-project). Single-package tools (pipx,
  dart pub, hex) set `removes_one_at_a_time` and get one command per package.
- `PackageManager.preview_remove(packages)` — a no-root dry-run for the managers that drag
  dependencies along: Pacman/AUR (`pacman -Rs --print`), DNF (`dnf remove --assumeno`), APT
  (`apt-get -s remove`). A failed dry-run (not installed, still required by something) blocks the
  removal even with `--yes`.
- `polyget remove -m MANAGER PKG... [--yes]`, plan-only by default like install/upgrade.
- **Still to verify on hardware:** the DNF transaction parser is written against dnf4 and dnf5
  output samples, not a live Asahi run; `pacman -Rs --print` on CachyOS.
- **Still to do:** GUI entry point (see "UI hooks" below); log removals in the history store
  (needs an `action` field so History/TUI don't render them as upgrades).

### 2. Janitor — orphans and caches (either; Pacman/DNF parts on hardware)
One page listing reclaimable space and a clean button per source: `pacman -Qdtq`,
`dnf autoremove`, `flatpak uninstall --unused`, `paccache -rk2`, `dnf clean packages`,
`cargo cache`, `npm cache`, pip/pipx caches. Each driver gets an optional
`get_cleanup_targets()` returning `{label, bytes, command}`; distro-specific commands go through
`app/core/distro.py`.

### 3. Restart-needed detection (both machines)
After an upgrade, report whether a reboot or service restart is needed:
`dnf needs-restarting -r` on Fedora; on Arch compare `uname -r` with the installed kernel
package (and `/usr/lib/modules`). Banner in the GUI, field in `polyget upgrade --json`.

### 4. Pre-upgrade snapshots (CachyOS first)
If snapper or timeshift is present, take a pre-upgrade snapshot before system-manager upgrades
and removals. CachyOS defaults to btrfs + snapper. Gives the Operation Journal & Rollback idea in
`2026-07-20-polyget-expansion.md` a real restore point.

## Tier 2 — machine-specific

**CachyOS beta**
- `.pacnew`/`.pacsave` tracker with diff and keep/replace actions.
- Arch news gate: read the archlinux.org news feed before a Pacman upgrade and warn on unread
  "manual intervention" items.
- Optimized-repo awareness (x86-64-v3/v4/znver4) — flag packages coming from the generic repo.
- `arch-audit` as an optional scanner for `polyget audit`.

**Asahi beta**
- Asahi stack panel: asahi kernel, m1n1/u-boot, asahi mesa, pending firmware updates.
- 16K page-size warnings for Flatpaks/binaries known to break (hooks into `app/core/arch.py`).
- `dnf history undo <id>` as a first rollback on Fedora.

## Tier 3 — usability (fits the redesign)
- Command palette (Ctrl+K) over pages and actions.
- Upgrade profiles (`polyget upgrade --profile dev`), shared with the GUI.
- Tray notifications with "Upgrade now" / "Snooze" actions.
- Per-manager health: locked db (`/var/lib/pacman/db.lck`), stale cache, expired keys.
- Duplicate detection: same tool installed from two managers, which one wins on `PATH`.
- Disk usage per manager.
- Keyboard-only navigation and screen-reader labels.

## Tier 4 — tooling for the branch workflow
- `polyget report`: distro, arch, managers, self-versions, last scan — attach to a port PR.
- Recorded command-output fixtures per machine (`tests/fixtures/{cachyos,asahi}/`) so the cloud
  environment can test the Pacman/DNF parsers against real captures.
- Blueprint diff between the two machines.

## UI hooks for the redesign
- Uninstall needs an Installed view, which the GUI doesn't have yet (the Store only searches).
  Cheapest path: a "Remove…" entry in the per-row `⋯` menu of the proposed Updates page, plus
  "Installed" as a Store filter. The confirm dialog should show `preview_remove()` output.
- `install_package()` in `app/ui/main_window.py` hardcodes install commands for five sources
  instead of calling `get_install_command()`, bypassing the drivers. Fold that in when the Store
  is reworked; uninstall should not copy the pattern.
