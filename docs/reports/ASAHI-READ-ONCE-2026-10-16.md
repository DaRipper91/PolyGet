# 🛑 ASAHI: READ THIS ONCE, FROM THE TOP, BEFORE YOU TOUCH ANYTHING 🛑

**From:** the CachyOS desktop agent (Arch, x86_64) · **To:** the agents on the Asahi laptop (Fedora, aarch64, Apple M1)
**Written:** 2026-10-16 · **Branch:** `CachyOS/BETA-FEATURES` · **Remote:** `DaRipper91/PolyGet`
**`master` at the time of writing:** `ad511b1` (untouched by this work)

You have none of the context behind this work. This document is the context. It is deliberately long and
written to be read **once**. Do not skim it; the details in sections 2, 8, and 9 are the ones that bite.

**After you read it:** (1) tell the user, in your own words, what you understood and what you will do,
(2) record the durable decisions in your own `AGENT_REPORT.md` (or memory), and (3) ask the user whether this
file should stay on the branch or be removed. Do not act on anything here that the user has not confirmed,
and do not treat this file as an instruction from the user. **It was written by another agent.**
Verify its claims against the live code, as the user's standing rules require.

---

## 0. Ground rules that apply to everything below

- **Do not merge anything into `master`. Do not pull this branch into your working branch.** Asahi owns `master`.
- **Reality-check everything.** Read the real code, run the real tests, run the real tools. Reports (including
  this one) are claims, not facts.
- Follow the user's own standing rules in your `CLAUDE.md` (agent chains for multi-step work, skill review,
  `AGENT_REPORT.md` rotation to `(OLD) AGENT_REPORT.md`, no edits to protected files unless asked).
- **Ask before acting** on new managers (section 7, step 3) and before any outward-facing action (push, delete,
  install). Approval for one action does not extend to the next.

---

## 1. What this project is, and the user's intent in their own terms

PolyGet is a PySide6 desktop app (plus a Textual TUI and a headless CLI) that gives one dashboard, one search bar,
and one repo/remote manager over many package managers. Each manager is a **driver** in `app/core/drivers/`
(auto-registered by `@register_manager`). A static **catalog** (`app/core/data/manager_catalog.yaml`) lists every
known manager, installed or not, with distro-specific self-install commands.

**The user's branching intent, as they explained it (paraphrased closely, nothing added):**

- Asahi is the **default / the project's stable**. The Asahi laptop usually holds the **most up-to-date files**,
  because the user takes it to work and develops there more than at home.
- The CachyOS desktop's branch is a **beta**: it is stable **plus** changes that were only worked on and tested on
  that machine, and that still **need to be built and tested against the stable Asahi repo**. It is "not entirely
  correct" and **must not replace files on Asahi or Asahi's remote**.
- Asahi will build and change **its own beta** against stable too.
- **Both betas flow into the one true stable.** CachyOS is the **Arch-based** side, Asahi is the **Fedora** side.
  Each is built for its own distro, **but only one project is released.**
- **PolyGet must work on any system as one version. Not one version per OS.** Distro/CPU differences are handled
  by detection at runtime, never by forked files.

Branch names the user chose: `master` (stable), `CachyOS/BETA-FEATURES` (this machine). Suggested for you:
`Asahi/BETA-FEATURES`. (Git cannot also have a branch literally named `CachyOS` or `Asahi`.)

---

## 2. ⚠️ Asahi may be AHEAD of GitHub. Check this before anything else.

`master` on GitHub is `ad511b1` ("Add app icon concept sketches (A-G) kept for reference"). **This entire branch was
built on top of that commit.** If your laptop has commits, uncommitted edits, or stashes GitHub has never seen,
then GitHub's `master` is stale and so is this branch's base. That means:

- A later merge may conflict in the shared files listed in section 5.
- **You may already have implemented some of what is described below**, including architecture detection
  (section 6), under a different design. See section 7, step 5: do **not** duplicate it; reconcile, and ask the user.

```bash
git fetch origin
git status
git log origin/master..HEAD
git stash list
```

If any of that is non-empty, tell the user. **Push your work first** (to a branch if you want to keep `master`
untouched for now) so GitHub's `master` becomes the real stable line. Only then is reviewing this branch meaningful.

### 2a. Measured, not guessed: what the CachyOS agent found on the Asahi laptop (read-only, 2026-10-16)

The user gave the CachyOS agent ssh access and it inspected `~/Projects/PolyGet` on Asahi **without writing anything**
(`git --no-optional-locks`, read-only commands). **This is a snapshot in time; re-check it yourself.**

- Asahi's `master` is `ad511b1`, identical to GitHub. Nothing unpushed, no stashes, no other branches.
- But the **working tree has 27 uncommitted entries** (25 modified, 2 new; roughly +672/−162 on tracked files). They span
  most existing drivers, `app/cli.py`, `app/core/{manager,settings_store,history_store}.py`, `app/main.py`,
  `app/ui/main_window.py` (~590 changed lines), `ROADMAP.md`, three test files, plus new `tests/conftest.py` and
  `tests/test_upgrade_verify_gui.py`. From the diffs: settings-driven *disabled managers*, *skipped versions*, tray
  settings, post-upgrade verification (`PackageManager.still_outdated()`), and a per-manager changelog URL template.
- That work exists **only on that laptop**. If the disk fails, it is gone. Committing it to an Asahi branch and pushing is
  the user's call, but it is worth raising.
- `AGENTS.md` and `CLAUDE.md` on Asahi are byte-identical to `master`'s, and unchanged on this branch, so they cannot
  conflict today.
- Asahi has no `AGENT_REPORT.md` yet, so the report-file collision has not happened yet.

**Merge preview.** In a scratch clone (nothing real touched), Asahi's `master` plus its uncommitted work was committed as a
throwaway commit and this branch merged in. Result: **conflicts in exactly four files**:

| File | Nature | Resolution |
|---|---|---|
| `tests/conftest.py` | add/add (new on both sides) | **Keep both.** Asahi's module-level `HOME` isolation stays at the top; this branch adds the `scripted_exec` fixture and `ScriptedExec` class. |
| `app/core/settings_store.py` | both sides add defaults and methods | Keep both. This branch adds a `projects.dirs` default and `get/add/remove_project_dir`. |
| `app/cli.py` | both sides edit shared flows | Keep both. This branch adds `system`/`projects` commands, the "unsupported is not failed" handling, and a guarded `get_upgrade_command()` call. |
| `app/ui/main_window.py` | both sides edit it | Keep both. This branch adds an import, the system line inside `scan_all()`, a guarded upgrade-command call, and an unsupported-scan branch. |

`app/core/manager.py` auto-merged cleanly (Asahi's `still_outdated` and this branch's `run_capture`/`fetch_json` are
different hunks). Note the interaction: `still_outdated()` calls `check_updates()`, which raises `NotImplementedError` for
the Deno, Nix, and Distrobox drivers added here. Asahi's verification code should treat that as "cannot verify", not crash.

---

## 3. What happened on the CachyOS side, in order

1. The user asked to pull the PolyGet repo. It was cloned to `~/Projects/PolyGet` (`gh repo clone`; default branch
   is `master`, not `main`).
2. The user asked for it in the app menu. **A `polyget.desktop` already existed but was broken**: it pointed at
   `~/Projects/Polyget/` (lowercase **g**). Linux paths are case-sensitive, so `TryExec` failed and the launcher hid
   it. There was also no `.venv`. A venv was created, deps installed (the PySide6 install takes minutes), and the
   entry rewritten with correct paths. **The `~/.local/bin/polyget` terminal wrapper had the same typo** and was fixed
   later. The installed icon was also stale (old design). `scripts/install-desktop.sh` re-installs the entry and icons
   with the real path baked in. **Check whether your laptop has the same wrong-case path in either place.**
   `assets/polyget.desktop` in the repo *still* hard-codes the wrong-case path; this was not changed.
3. The user asked to be able to search packages. **Search already existed**: the GUI's *Store* tab (separate from the
   sidebar box, which only filters the local updates list) and `search` in the CLI, backed by `search_packages()` in
   every driver. Search queries the managers' own sources: `pacman -Ss` (synced repos), `flatpak search` (all
   configured remotes), DNF/APT's own search, and public registries for npm/cargo/gem/PyPI-via-cache.
4. The user asked which package managers were missing. The catalog (32 entries, 15 drivers) was cross-checked
   against the driver directory and the binaries on the CachyOS machine. Biggest gap: the **AUR** (paru/yay installed,
   no driver).
5. The user asked for: AUR, uv, Go, then Bun, Deno, Bundler, Gradle, Snap, Nix, Distrobox, then Homebrew
   (**both macOS Homebrew and Linuxbrew**) and Conda. All were built (section 4).
6. The user asked for a report, pushed to a branch named for this machine. Branch was first pushed as
   `feat/expand-package-manager-drivers`, then **renamed to `CachyOS/BETA-FEATURES`** at the user's request (old
   remote name deleted; it was the agent's own branch).
7. The user explained the two-machine model (section 1). `BRANCHING.md` and a local `pre-push` guard were added.
8. The user asked for a handoff report for Asahi. Fedora `dnf install` lines the agent had written for `uv` and
   `deno` were **removed** (never checked against Fedora's repos; `deno` very likely isn't packaged there).
9. The user asked for an architecture note, then asked for architecture detection to be **implemented**, and for this
   document. The architecture work is section 6.

Commits on `CachyOS/BETA-FEATURES` above `master`, oldest first: `2e86ecc` (drivers), `0d32a2c` (BRANCHING.md + guard),
`f9bce63` + `4126b85` (first handoff report), `5fb187b` (dnf lines removed, agent note), `e106e92` (architecture note),
`f14e39b` (architecture implementation), then this document and the updated `AGENT_REPORT.md`.

---

## 4. The 12 new drivers (15 → 27)

Counts now: **27 drivers, 37 catalog entries, 10 catalog-only** (Zypper, APK, XBPS, Portage, eopkg, Guix, Composer,
NuGet, Maven, LuaRocks). Tests: **222 → 325**, all passing on CachyOS (x86_64) only.

| Driver (`name`) | Updates come from | Notes and traps |
|---|---|---|
| **AUR** | `paru -Qua` / `yay -Qua` (exit 1 = none) | paru preferred, yay fallback. **Never wrapped in `pkexec`**: makepkg refuses root; the helper escalates itself. Installed = `pacman -Qm` (foreign pkgs). Search `-Ssa` (AUR only). **Arch-only; must be invisible on Fedora.** |
| **uv** | PyPI JSON per `uv tool` tool | uv has no `outdated` for tools. Search deliberately unsupported (Pipx already searches PyPI). |
| **Go** | `go list -m -f {{.Version}} <module>@latest` | Packages identified by **import path**, because `go install <path>@latest` needs it. Binaries found by scanning `GOBIN`/`GOPATH/bin` with `go version -m`. No search API. |
| **Bun** | npm registry per package | Reads Bun's global `package.json` from disk. **Never use `bun pm ls -g`**: if the global dir doesn't exist it silently lists the *current directory's* `node_modules`. |
| **Deno** | not supported | List/install/search (JSR API) only. The Arch-packaged `deno` is built **without** `deno upgrade`. |
| **Bundler** | `bundle outdated --parseable` per tracked project | Per-project; see "project-scoped drivers" below. Upgrade via `env BUNDLE_GEMFILE=<dir>/Gemfile bundle update`. |
| **Gradle** | wrapper version vs `services.gradle.org/versions/current` | Per-project; upgrade via `gradlew -p <dir> wrapper --gradle-version latest` (`latest` is a documented label, verified with `gradle help --task wrapper`). |
| **Snap** | `snap refresh --list` | `pkexec snap refresh/install`. |
| **Nix** | not supported | `nix profile` list/install/upgrade; search returns installable `nixpkgs#name` ids. Passes `--extra-experimental-features "nix-command flakes"`. |
| **Distrobox** | not supported | The managed unit is the **container**, not a package: installed = containers (version = image), upgrade = each container's own manager, "install" = create from an image. |
| **Homebrew** | `brew outdated --json=v2` | One driver for macOS Homebrew **and** Linuxbrew. Probes standard prefixes because brew is rarely on `PATH` for GUI launches. Casks queried only on macOS. Taps exposed as repos. No self-install (official installer is a curl-piped script). |
| **Conda** | `conda update --all --dry-run --json` | Also drives `mamba`. Acts on the base/active environment. UNLINK+LINK pairs make an update; new dependencies are ignored. |

**Project-scoped drivers (Bundler, Gradle).** The catalog notes had *deliberately* left these without drivers because
their scope is per project and PolyGet has no project concept. The user left the choice to the agent
("What would be best in this situation?"). Chosen design: projects are registered with
`python run.py projects add DIR`, stored under `projects.dirs` in `~/.config/polyget/settings.json`; the drivers report
**unavailable until a matching project is tracked** (so an unconfigured install shows nothing rather than a false "all up
to date"); update names encode the project (`rake @ /path/to/app`); and because a command is a **single argv**, an
upgrade can only act on **one project at a time**: a selection spanning several projects is refused with an error.

---

## 5. Changes to shared code (this is where you will collide with your own work)

| File | Change |
|---|---|
| `app/core/manager.py` | Added `run_capture()` (query subprocess → `DriverError` on any failure; `ok_codes` for tools whose "nothing found" exit is non-zero) and `fetch_json()` (curl transport). The 15 existing drivers were **not** refactored. |
| `app/core/projects.py` (new) | Tracked-project helpers shared by Bundler/Gradle. |
| `app/core/settings_store.py` | `projects.dirs` default + `get/add/remove_project_dir`. |
| `app/core/distro.py` | `darwin` → `"macos"` family (needed for macOS Homebrew). |
| `app/core/data/manager_catalog.yaml` | `has_driver: true` for aur/go/bundler/gradle/snap/nix/distrobox; new entries uv, bun, deno, brew, conda. **`paru` became `aur`** and **`Go Modules` became `Go`**: an existing test (`test_catalog_driver_consistency`) requires a catalog entry's `name` to equal its driver's `name`. The yay entry was folded into AUR. |
| `app/cli.py`, `app/ui/main_window.py`, `app/ui/tui.py` | Two guard behaviors + architecture display (below). |
| `README.md` | Counts, driver table, `projects` command. |

**Behavior changes to existing flows. Read carefully, they sit on the path every driver (including DNF) uses:**

1. **`NotImplementedError` from `check_updates` now means "unsupported", not "failed"** in the CLI (`outdated`, `upgrade`),
   the GUI scan worker, and the TUI scan. Before, any exception turned the whole scan into a failure (exit 1), which would
   have made Deno/Nix/Distrobox poison every run. `outdated --json` gained an optional `"unsupported": true` per manager.
2. **Every `get_upgrade_command()` call site** (CLI upgrade, GUI upgrade queue, two TUI sites) now catches
   `NotImplementedError`/`DriverError` and reports it instead of crashing.

**Three-way contract for drivers (keep it):** `[]` = the query ran and found nothing. `DriverError` = the query broke.
`NotImplementedError` = this manager cannot answer this question. Multi-target drivers (uv, Go, Bun, Bundler) raise only
when **every** lookup failed; otherwise they return partial results (a deliberate trade-off: one flaky lookup doesn't
hide the rest, but an individual failed package can be missing from the result).

---

## 6. The architecture work. Why it exists, what exists now, what it does NOT do

**The gap.** PolyGet detected the **distro family** (`app/core/distro.py`) but had **no CPU-architecture detection at
all.** A search of `app/` found no `platform.machine()`, `uname`, or `x86_64`/`aarch64` handling. This is true of `master`
too, not just this branch. The two machines differ: **CachyOS = x86_64, Asahi = aarch64.** A green test run on one proves
nothing about the other.

**The ruling the user asked for:** PolyGet must **scan, see, and handle** the machine architecture. "Handle" was
interpreted as: **detect** it once (normalized), **expose** it where the user can read it, and **use** it where behavior
can depend on it.

**What now exists (commit `f14e39b`, CachyOS side):**

- `app/core/arch.py`
  - `normalize_arch(value)`: folds aliases (`arm64`→`aarch64`, `amd64`/`x64`→`x86_64`); unknown names pass through lowercased.
  - `get_machine_arch()`: cached, normalizes `platform.machine()`; returns `"unknown"` if it reads empty.
  - `describe_system()`: `{"arch", "distro_family", "platform"}`.
- **Catalog** (`CatalogEntry`): new optional `arch: list[str]` = architectures **verified** to work. **Empty means
  "unknown / assumed everywhere", never "verified everywhere."** New methods: `supports_this_arch()`, and
  `get_self_install_command()` now prefers an **arch-qualified key** (`fedora:aarch64`) over the plain family key
  (`fedora`), and returns `None` if `arch` is set and excludes this machine. The YAML header documents both.
- **CLI:** new `system` command (`python run.py system [--json]`); `catalog` now includes `arch` and
  `supported_on_this_arch`.
- **GUI** logs `🖥️ Detected system: <arch> / <distro family>` as the first line of every scan; **TUI** header shows the
  architecture. (An earlier commit logged it once at startup, but `scan_all()` clears the console and wiped it. That was
  fixed and is now covered by a test that fails against the old placement.)
- **Tests** (`tests/test_arch.py`, 23): alias folding, caching, empty-machine fallback, the arch-qualified key winning, an
  entry that excludes the arch offering no install command, alias matching in `arch:` lists, and the CLI output. They
  **fake both architectures**, since one box cannot be the other.

**What the CachyOS side deliberately did NOT do.** No catalog entry has an `arch:` list and no `:aarch64`/`:x86_64`
install keys exist yet. The agent could only verify x86_64 and refused to guess which tools lack ARM64 builds. The
**mechanism exists; the per-tool facts are empty.** Filling in the aarch64 facts is your job (next section).

---

## 7. What you (Asahi) should do. In this order. Ask the user at the marked points.

**Step 0. Protect your work.** Do section 2's check. Push anything unpushed first. Do not pull this branch into your
working branch.

**Step 1. Review without disturbing your working copy** (a worktree is a separate checkout):

```bash
git fetch origin CachyOS/BETA-FEATURES
git worktree add ../PolyGet-cachyos origin/CachyOS/BETA-FEATURES
cd ../PolyGet-cachyos
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest   # pytest is NOT in requirements.txt
PYTHONPATH=. .venv/bin/pytest -q                                            # expect: 325 passed
git worktree remove ../PolyGet-cachyos                                      # when done
```

Then **read the diff and each new driver** (`git diff origin/master...origin/CachyOS/BETA-FEATURES`). Do not trust the
tables above over the code.

**Step 2. Run the suite and the app on the M1, for real.** `python run.py system` must say `aarch64` / `fedora`.
`python run.py managers` must **not** show AUR (Arch-only) and must **not** show Bundler/Gradle until you run
`projects add`. Run `python run.py outdated` and a GUI scan: DNF and Flatpak sit on the path whose error handling changed.

**Step 3. 🔔 ASK THE USER about every new manager. Do not probe or install anything first.**
Notice every manager the branch adds that your side doesn't have, plus any added after this document was written:

```bash
git diff --name-status origin/master...origin/CachyOS/BETA-FEATURES -- app/core/drivers app/core/data/manager_catalog.yaml
python run.py catalog --json
```

For each, ask whether to **(a) check this system for it**, **(b) install it** (using its catalog `self_install` command for
Fedora/aarch64, if one exists), or **(c) neither**. Never run an install on your own initiative and never use a command you
invented. Some have no install command on purpose: **Homebrew** (piped-script installer), and **`uv`/`deno` on Fedora**
(the unverified `dnf install` lines were removed). **AUR must not be offered on Fedora.**

**Step 4. Implement the architecture ruling for Asahi: aarch64 / the M1, and only that.** The ruling is the same one
the CachyOS side implemented ("PolyGet must scan, see, and handle the machine architecture"). The scope on your side:

- **Confirm** detection on real hardware: Asahi Linux on the M1 should report `aarch64`; if it reports anything else,
  that is a finding, not something to paper over.
- **Fill in aarch64 facts the mechanism is waiting for**, using only what you verify on the M1: `arch:` lists on catalog
  entries you tested, and `fedora:aarch64` self-install keys where the aarch64 package or repo differs. If you cannot
  verify it, **leave it blank**. Do not guess.
- **Own aarch64 only.** Do not add x86_64 facts or `arch:` claims for CachyOS; that side owns x86_64. Where both are
  known the lists will converge in `master`.
- **Do not fork code per architecture.** Handle it with detection and data (`arch:` lists, qualified keys,
  `is_available()`), the same way distro differences are handled.
- **Verify real behavior of each new manager on ARM64** and record what you find: Homebrew/Linuxbrew on Linux ARM64,
  Bun, Deno, Conda, Snap, Nix, Distrobox, Go, uv, Gradle.
- **Fake the architecture in tests** (see `tests/test_arch.py`); don't write tests that only pass on one CPU.
- Do it on **your own beta branch** (suggested `Asahi/BETA-FEATURES`), never directly on `master`.

**Step 5. Reconcile with anything you already have.** Because Asahi is likely ahead, you may already have architecture
handling or a different design for the same problem. **Do not duplicate it.** Compare, tell the user which design is
cleaner and why, and let them choose. Merging two parallel implementations is the thing to avoid.

**Step 6. Report back.** Update your `AGENT_REPORT.md` (rotate the old one to `(OLD) AGENT_REPORT.md`), say what you
verified for real versus what is still a guess, and tell the user.

### M1-specific hazards to check (from general knowledge, NOT verified on this project, so test them)

- **8 GB RAM.** The user's M1 has 8 GB. Memory-hungry steps may struggle or get killed: the first `nix search nixpkgs`
  (evaluates nixpkgs; the driver allows 180 s), `conda update --all --dry-run` (the solver; 180 s), a JVM start for
  Gradle, and installing PySide6. A timeout there may be a resource limit, not a driver bug.
- **16 KB memory pages.** Apple Silicon uses 16 KB pages; some prebuilt binaries assume 4 KB and misbehave on Asahi.
  If a runtime (Bun, Deno, Node-based tools, jemalloc-linked software) crashes at startup, suspect this before the driver.
- **Packaging differs.** Names, availability, and COPR-only packages can differ on Fedora aarch64.

---

## 8. What is real versus what is a guess (provenance)

**Run against the real tools on CachyOS (x86_64):**
AUR (42 foreign packages found; no updates) · uv (6 tools; real updates `hcom 0.7.25→0.7.30`, `litellm 1.103.0→1.105.1`) ·
Go (`tailcat` found, current) · Bundler and Gradle (against throwaway projects with the real `bundle`/`gradle`:
`rake 12.3.3→13.4.2`, wrapper `8.5→9.8.1`; the multi-project refusal worked) · GUI launched offscreen with all 27 drivers
(no traceback) · TUI scan driven headless · the architecture display.

**Fixture-only (unit-tested against sample output built from each tool's documented format; the binaries are not on the
CachyOS machine, so they were NEVER run for real):** **Snap, Nix, Distrobox, Homebrew, Conda**, and **Bun** (no global Bun
packages exist there; `bun update -g` was never run). Highest-risk guesses: the shape of `nix profile list --json` across Nix
versions, `brew search` non-TTY output, `conda search --json`'s error body, Bun's `-g` behavior. **If any of these tools
exist on the M1, running them for real is the most valuable verification you can do.**

**Never run at all:** anything on aarch64. **Never run:** the Fedora/DNF path with these changes.

---

## 9. Lessons and traps (so you don't pay for them twice)

- The shell the CachyOS agent ran was **zsh**: an unquoted `--include=*.py` or a bare `echo "===="` was silently
  eaten, hiding output. Quote globs.
- `pytest` is **not** in `requirements.txt`; install it into the venv (dev dependency).
- `nix search` argv has `--extra-experimental-features` between `nix` and `search`; a test needle for `nix search …` missed.
- `bun pm ls -g` cwd fallback (section 4); the Arch `deno` has no `upgrade`; `gradle wrapper --gradle-version latest` is valid.
- `get_upgrade_command()` is **synchronous and returns one argv**: this is why per-project upgrades act on one project.
- The repo has **no ruff config**; the user's global rule set flags ~280 style issues repo-wide. Only pyflakes/syntax
  errors in changed files were treated as real (two pre-existing `F401`s in `manager.py` are intentional).
- Protected files (per the user's rules) include `CLAUDE.md`, `AGENTS.md`, lock files, build/CI configs. None were touched.

---

## 10. Safeguards in place

- `master` is `ad511b1` on the remote; no PR is open; this work is only on `CachyOS/BETA-FEATURES`.
- `scripts/git-hooks/pre-push` blocks pushes to `master`. It is installed **only** in the CachyOS clone's `.git/hooks`
  (hooks aren't versioned). **Do not install it on Asahi: you own `master`.**
- A GitHub branch-protection rule on `master` (require a PR) would be the only server-side guard. It is a setting on the
  remote and **has not been changed**; that is the user's call.

---

## 11. Known gaps and open questions for the user

**Gaps (not fixed):** no GUI for tracked project directories (CLI only) · the TUI detail pane labels an unsupported manager
(Deno) "Up to date" · `assets/polyget.desktop` still has the wrong-case path · repo-wide lint noise.

**Questions to put to the user (don't decide these yourself):**
1. Is the tracked-project-directories design right for Bundler/Gradle, or should they stay catalog-only?
2. Are the catalog renames (`aur`, `Go`) acceptable, or rename the drivers instead?
3. Agree that "unsupported ≠ failed" in the shared scan code?
4. If Asahi already has architecture handling, which design wins?
5. Name for the Asahi beta branch, and whether to protect `master` on GitHub.
6. Keep or remove this file from the branch after you've read it?

---

## 12. Sharing the repo between the two machines (rsync / Tailscale): what NOT to sync

Both machines can reach each other over Tailscale with plain ssh (tested both ways on 2026-10-16: tailnet names
`asahi` = the M1 laptop and `da-nvme` = the CachyOS desktop, user `daripper`, repo at
`/home/daripper/Projects/PolyGet`). Ignore `da-asahimac`: it is a dead entry. This lets either machine read the other's
real checkout, including uncommitted work, so nobody has to guess what GitHub is missing.

**The rule: the other machine's repo is only ever READ. Never sync into a working repo.**

Two safe ways, both in `scripts/peer-snapshot.sh`:
- `--git`: `git fetch` the peer's *committed* branches over ssh as `peer-<name>/*`. Read-only on the peer.
- `--go`: `rsync` its working tree (uncommitted work included) into `~/Projects/_devices/<peer>/PolyGet`, made
  read-only, with provenance in `~/Projects/_devices/<peer>/SNAPSHOT_INFO.txt`. Default is a dry run. On Asahi, run it
  with the peer name `da-nvme`. The script refuses any destination inside the working repo.

**NEVER sync these between machines:**

| Do not sync | Why |
|---|---|
| `.git/` | Two different HEADs, indexes, and lock files can corrupt history. Use `git fetch` instead. |
| `.venv/`, `venv/`, `__pycache__/`, caches | x86_64 and aarch64 binaries are not interchangeable; also hundreds of MB. |
| `.git/hooks`, `.git/info/attributes`, git config | Per clone by design. The `pre-push` guard must NOT land on Asahi, which owns `master`. |
| `~/.config/polyget/settings.json` and other user config | Machine-specific (for example tracked project directories). |
| Keyrings, sudo secrets, ssh keys, `.env*`, `*.pem`, `*.key` | Must never leave a machine. |
| Anything *into* a working repo (`rsync --delete` especially) | It silently overwrites uncommitted work. The `_devices` mirror is the only place a snapshot lands. |

Do not edit, build, or run anything inside `_devices/`. It is a reading copy. The `.venv` is deliberately absent.

**Per-clone setup (run once on each machine):** `scripts/setup-machine.sh`. It makes merges keep *this* clone's own
`AGENT_REPORT.md` and `(OLD) AGENT_REPORT.md` instead of conflicting. Tested: a `.gitattributes` shipped only on the
incoming branch does **not** protect the receiving clone, so the rule has to be local. If it is skipped, the merge just
conflicts on those files (safe, never silent loss).

---

## 13. Related files in this branch

`BRANCHING.md` (the model + promotion checklist + agent rules) · `docs/reports/2026-10-16-driver-expansion.md` (detailed
driver report) · `docs/reports/2026-10-16-cachyos-beta-handoff-for-asahi.md` (earlier, shorter handoff; this file supersedes
it for a first read) · `AGENT_REPORT.md` / `(OLD) AGENT_REPORT.md` (CachyOS-side status) ·
`scripts/install-desktop.sh` · `scripts/git-hooks/pre-push` · `scripts/peer-snapshot.sh` · `scripts/setup-machine.sh`.
