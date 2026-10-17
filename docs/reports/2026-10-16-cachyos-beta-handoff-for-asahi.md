# CachyOS Beta → Asahi Review Handoff

**Branch under review:** `CachyOS/BETA-FEATURES` · **Commits on top of `master`:** `2e86ecc` (drivers), `0d32a2c` (branching doc + guard), plus the commit carrying this report ·
**Written:** 2026-10-16 on the CachyOS desktop (Arch, x86_64) · **Reader:** the Asahi laptop (Fedora, aarch64)

> 📌 **Asahi agents: read `ASAHI-READ-ONCE-2026-10-16.md` (same folder) first.** It is the complete, current
> version and supersedes this shorter handoff, which was written before architecture detection existed.
>
> **Nothing here has been merged into `master`, and nothing should be until Asahi has reviewed it.**
> `master` on GitHub is still `ad511b1`. This branch adds one feature commit and one docs/tooling commit on top of it.

---

## 📣 NOTE FOR AGENTS (read before doing anything else)

If you are an AI agent asked to review this branch, do these in order. Do not skip to the summary.

1. **Review the code, not just this report.** Reports go stale and are written by an agent that may be wrong.
   Read the actual diff (`git diff origin/master...origin/CachyOS/BETA-FEATURES`), read each new driver in
   `app/core/drivers/`, and run the test suite yourself. Verify claims against the live code and system.
2. **Notice every new manager.** Compare what the branch adds against what is on your side:
   ```bash
   git diff --name-status origin/master...origin/CachyOS/BETA-FEATURES -- app/core/drivers app/core/data/manager_catalog.yaml
   python run.py catalog --json      # id, name, installed, has_driver, self_install for every manager
   ```
   The managers new in this branch are: **AUR** (`paru`/`yay`), **uv**, **Go**, **Bun**, **Deno**,
   **Bundler** (`bundle`), **Gradle**, **Snap**, **Nix**, **Distrobox**, **Homebrew** (`brew`), **Conda**.
   Also look for any manager added *after* this report was written; list what you find rather than
   assuming this list is complete.
3. **Ask the user before acting on any new manager.** For each one, ask whether you should
   **(a) check this system for it** (is the binary present, does the driver work against the real tool) or
   **(b) install it** (using its catalog `self_install` command for this distro, if one exists), or **neither**.
   - Do not probe, install, or run a new manager's commands until the user answers.
   - Never run an install command on your own initiative, and never use a command you made up.
   - Some managers have no install command here on purpose: Homebrew (its installer is a piped shell
     script), and `uv` / `deno` on Fedora (see section 6, item 2). Say so and let the user decide.
   - **AUR is Arch-only.** On Fedora, do not offer to install it; it is expected to be hidden.
4. **Check the machine architecture, and make sure PolyGet scans, sees, and handles it.**
   - The two machines differ: **CachyOS is x86_64; Asahi is aarch64** (Apple Silicon running Linux ARM64).
     Tests passing on x86_64 prove nothing about aarch64, and the reverse.
   - **Known gap (verified against the code at `5fb187b`, re-verify it):** PolyGet detects the *distro family*
     (`app/core/distro.py`) but has **no CPU-architecture detection**. A search of `app/` finds no
     `platform.machine()`, `uname`, or `aarch64`/`x86_64` handling. This predates this branch and is also true of `master`.
   - Confirm for yourself with `uname -m` and `python3 -c "import platform; print(platform.machine())"`, then
     confirm what PolyGet itself reports. If it does not detect and expose the architecture, that is a gap
     to close, not to work around.
   - "Handling" means: (a) **detect** it once, normalized (`aarch64`/`arm64` and `x86_64`/`amd64` are aliases),
     next to `get_distro_family()`; (b) **see** it, i.e. surface it where the user can read it, such as `managers`,
     `catalog`, or the GUI/TUI; (c) **use** it wherever behavior can depend on it: whether a manager or its package
     exists for this CPU, catalog `self_install` commands that need a different package or repo per architecture,
     and results that are architecture-specific (Nix `legacyPackages.<system>`, Conda subdirs, Flatpak/Snap builds).
   - Do **not** guess which tools lack an ARM64 build. Check on the real machine. Examples to verify, not assume:
     Homebrew/Linuxbrew on Linux ARM64, Bun, Deno, Conda, Snap, Nix.
   - Do the work on **your own beta branch**, with tests that run under both architectures (fake the machine
     value in unit tests, since CI on one box cannot be the other). Do not change `master` directly.
5. **Do not merge into `master`**, and do not pull this branch into a working branch, as part of a review.

---

## 1. TL;DR

- This branch adds **12 package-manager drivers** (15 → 27) plus the shared plumbing they need.
  See `git diff --stat origin/master...HEAD` for the exact size. Test count went **222 → 325, all passing on CachyOS** (x86_64 only).
- It is a **beta for the Arch side**. It must be built and tested against the stable line on **Asahi** before
  any of it reaches `master`.
- **Asahi probably has newer files than GitHub's `master`.** This branch was built on `ad511b1`, which may be
  stale. Check for that *before* reading the diff (section 3).
- Section 6 lists **what only Asahi can verify**, including Fedora self-install commands for
  `uv` and `deno`, which were removed as unverified (section 6, item 2).

## 2. The project model

PolyGet is **one project, one release, running on any system.** No per-OS forks.

| Branch | Owner | Meaning |
|---|---|---|
| `master` | Asahi (Fedora) | Stable. Only code proven on **both** Asahi and CachyOS. |
| `CachyOS/BETA-FEATURES` | CachyOS desktop (Arch) | Stable + changes worked on and tested only on that machine. |
| `Asahi/BETA-FEATURES` (confirmed) | Asahi laptop | Same, from the Fedora side. |

Both betas are built against stable and merge into `master` once proven on the other machine. Distro
differences are handled by runtime detection (`is_available()`, `app/core/distro.py`, catalog keys per
distro family), never by forking files. Full rules and the promotion checklist: `BRANCHING.md` on this branch.

## 3. Do this first: is GitHub's `master` stale?

Most development happens on Asahi, so the laptop may hold commits or edits GitHub has never seen.

```bash
git fetch origin
git status                      # uncommitted work?
git log origin/master..HEAD     # commits GitHub does not have?
git stash list                  # anything parked?
```

If any of that is non-empty, **push it first** (to a branch if you'd rather not touch `master` yet). Only
then does `master` represent the real stable line and only then is a merge from this branch meaningful.

## 4. Reviewing this branch without disturbing your working copy

A worktree gives you a separate checkout; your current branch and uncommitted files are untouched.

```bash
git fetch origin CachyOS/BETA-FEATURES
git worktree add ../PolyGet-cachyos origin/CachyOS/BETA-FEATURES
cd ../PolyGet-cachyos
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
PYTHONPATH=. .venv/bin/pytest -q          # expect: 325 passed
```

Remove it afterwards with `git worktree remove ../PolyGet-cachyos`. **Do not** `git pull` this branch into
your working branch, and do not merge it into `master` as part of reviewing.

## 5. What changed

Full detail is in `docs/reports/2026-10-16-driver-expansion.md`. Summary:

**New drivers** (`app/core/drivers/`): AUR (paru/yay), uv, Go, Bun, Deno, Bundler, Gradle, Snap, Nix,
Distrobox, Homebrew (macOS + Linuxbrew in one driver), Conda.

**Shared plumbing**
- `app/core/manager.py`: `run_capture()` and `fetch_json()` helpers. The 15 existing drivers were *not* refactored.
- `app/core/projects.py` + `projects.dirs` setting + `projects` CLI command: Bundler and Gradle have no global
  package list, so they scan directories you register (`python run.py projects add DIR`) and stay hidden until one exists.
- `app/core/distro.py`: `darwin` → `"macos"` family.
- Catalog: `has_driver: true` for aur/go/bundler/gradle/snap/nix/distrobox; new entries uv, bun, deno, brew, conda.
  `paru` became `aur` and `Go Modules` became `Go` (an existing test requires catalog name == driver name).

**Behavior changes to existing code: read these carefully, they touch files you also edit**
1. `NotImplementedError` from `check_updates` now means **"unsupported", not "failed"** in the CLI
   (`outdated`, `upgrade`), the GUI scan worker, and the TUI scan. Previously any exception was a failure,
   which would have turned every scan red for Deno, Nix, and Distrobox.
2. Every `get_upgrade_command()` call site (CLI upgrade, GUI upgrade queue, both TUI sites) now catches
   `NotImplementedError`/`DriverError` and reports it instead of crashing. Bundler/Gradle can legitimately
   raise when an upgrade selection spans several projects.
3. `cmd_outdated` JSON gained an optional `"unsupported": true` flag on a manager entry.

Files in your likely conflict zone: `app/core/manager.py`, `app/cli.py`, `app/ui/main_window.py`,
`app/ui/tui.py`, `app/core/data/manager_catalog.yaml`, `README.md`.

## 6. What only Asahi can verify

| # | Item | Why it matters |
|---|---|---|
| 1 | **Run the full test suite on Fedora/aarch64.** | Only x86_64 Arch has run it. |
| 2 | **Fedora self-install for `uv` and `deno`.** | The unverified `dnf install` lines I first wrote for these two were **removed**, so they currently have no Fedora self-install command (Arch only). If you want one, find the real Fedora package or COPR yourself and add it. Do not guess. |
| 3 | **DNF/Flatpak still behave.** | The scan/upgrade guards in section 5 sit on the path every driver uses, including DNF. Run `python run.py outdated` and a GUI scan on the laptop. |
| 4 | **Real runs of Snap, Nix, Distrobox, Homebrew, Conda, Bun** if installed. | None of these exist on the CachyOS machine. Their parsers are tested against **fixtures built from documentation only**. Highest-risk guesses: `nix profile list --json` shape across versions, `brew search` non-TTY output, `conda search --json` error body, `bun update -g`. |
| 5 | **Distrobox in particular.** | Asahi is the likelier machine to have it, and it manages *containers*, not packages (installed = containers, upgrade = each container's own manager, install = create from an image). Confirm that is the behavior you want. |
| 6 | **aarch64 behavior and architecture handling.** | CachyOS is x86_64, Asahi is aarch64, and PolyGet has **no CPU-architecture detection** (see the agent note, item 4). Verify what each new manager does on ARM64: Bun, Deno, Conda, Snap, Nix, Homebrew/Linuxbrew availability and package builds. |
| 7 | **Hidden-by-design drivers.** | AUR must be invisible on Fedora; Bundler/Gradle must stay hidden until `projects add`. Confirm `python run.py managers` shows no stray entries. |

Verified for real on CachyOS: AUR, uv, Go (live tools); Bundler and Gradle (real `bundle`/`gradle` against
throwaway projects); GUI launched offscreen with all 27 drivers; TUI scan driven headless.

## 7. Decisions for the Asahi side

1. **Bundler/Gradle design.** Tracked project directories, one project per upgrade command, hidden until
   configured. The original catalog notes had *deliberately* left these driverless because they are per-project.
   Is this the right compromise, or should they stay catalog-only?
2. **Catalog renames** (`aur`, `Go`): acceptable, or do you prefer renaming the drivers instead?
3. **Unsupported ≠ failed** (section 5, item 1): agree with the semantics change in shared scan code?
4. ~~Branch naming for the Asahi beta~~ Settled: `Asahi/BETA-FEATURES`.
5. **GitHub branch protection** on `master` (require a PR). The local `pre-push` guard only covers this one clone.

## 8. Known gaps (not fixed)

- **No CPU-architecture detection anywhere in PolyGet** (distro family only). Not introduced by this branch, but this
  work added managers whose availability and packages vary by architecture. See the agent note, item 4.
- No GUI to manage tracked project directories (CLI only).
- The TUI detail pane labels an unsupported manager "Up to date" (it only tells empty from non-empty).
- `assets/polyget.desktop` still hard-codes `~/Projects/Polyget/` (wrong case); each machine's installed copy
  is produced by `scripts/install-desktop.sh`, which bakes in the real path.
- Lint: the repo has no ruff config; no pyflakes/syntax errors in changed files, but ~280 style findings exist repo-wide.

## 9. Safeguards in place

- Remote `master` untouched at `ad511b1`; no PR open; this branch is separate.
- `scripts/git-hooks/pre-push` (installed on the CachyOS clone only) refuses pushes to `master`.
  **Do not install it on Asahi**: Asahi owns the stable line.
