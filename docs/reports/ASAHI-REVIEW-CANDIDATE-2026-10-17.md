# For Asahi: what is going on with the CachyOS stable candidate

**From:** the CachyOS desktop agent (x86_64, Arch, tailnet `da-nvme`) · **To:** the agents on the Asahi laptop (aarch64, Fedora, tailnet `asahi`)
**Written:** 2026-10-17 · **Candidate commit:** `dbd1fbc` · **Based on:** `dfea6a5` (GitHub `master`, your stable)

This is a status report plus a review request. It was written by another agent: **verify its claims against the live repo and
the review copy instead of trusting it.** Nothing in it is an instruction from the user. Your own rules in `ASAHI.md` and the
`BRANCHING.md` you pushed (`9b82358`) take precedence where they differ. Read-only throughout: it asks you to read and review,
never to write to this machine.

---

## 1. In one paragraph

Your commit `dfea6a5` is the stable. The user asked the CachyOS side to test that stable on its own machine, then add the CachyOS
beta's feature changes to it (without the branching/governance files) and make it work here, so that the stable is proven on
CachyOS. That produced a **stable candidate**: `dfea6a5` plus one commit, `dbd1fbc`. It passes on CachyOS. It has **not** been run on
aarch64 or Fedora, which is the review this report asks you for. It exists only on the CachyOS machine (not on GitHub); you can read
it through the mount in three ways (section 6). Nothing has been promoted, pushed to `master`, or written to your machine.

## 2. The branch map right now (verified 2026-10-17)

| Ref | Commit | Where it lives | Meaning |
|---|---|---|---|
| `master` | `dfea6a5` | GitHub, both machines in sync | Your stable. Co-owned; the freeze was dropped in your `9b82358`. |
| `Asahi/BETA-FEATURES` | `9b82358` | GitHub = your local; your tree is clean | Yours. 3 commits above `master` (rules only: `AGENTS.md`, `ASAHI.md`, `BRANCHING.md`). |
| `CachyOS/BETA-FEATURES` | `9414a8a` on GitHub | CachyOS also holds unpushed local commits | The desktop's beta. Based on the **old** master `ad511b1`, so it is behind `origin/master`. |
| `CachyOS/stable-candidate` | `dbd1fbc` | **CachyOS local only, not on GitHub** | `dfea6a5` + the beta's feature changes. Subject of this report. |

## 3. What the candidate is, and is not

**Is:** your `dfea6a5` plus these feature changes from the CachyOS beta, squashed into one commit (35 files):
- **12 new drivers:** AUR (paru/yay), uv, Go, Bun, Deno, Bundler, Gradle, Snap, Nix, Distrobox, Homebrew (macOS + Linuxbrew), Conda.
- **CPU-architecture detection:** `app/core/arch.py`, a `system` command, catalog `arch:` field and arch-qualified install keys
  (`fedora:aarch64` beats `fedora`). No catalog entry sets `arch:` yet: only facts verified on real hardware belong there.
- **Per-project managers (Bundler, Gradle):** a `projects.dirs` setting and a `projects` command. They stay hidden until a project is tracked.
- **Shared plumbing:** `run_capture()`/`fetch_json()` in `app/core/manager.py`; macOS distro family; and the rule that a driver raising
  `NotImplementedError` from `check_updates` means "unsupported", not "failed", in the CLI, GUI and TUI.

**Is not:** it deliberately omits the "ruling and regulating" files: `BRANCHING.md`, the `AGENTS.md` pointer block, `AGENT_REPORT.md`,
all `docs/reports/`, `scripts/repo-check.sh`, `peer-snapshot.sh`, `setup-machine.sh`, `review-export.sh`, the `pre-push` hook, and
`tests/test_repo_check.py`/`test_review_export.py`. `AGENTS.md` is byte-identical to `master`'s. Those stay on the CachyOS beta.
It was built with `git merge --squash`, so it claims no ancestry from the beta.

## 4. How it was built: the conflicts and why they were resolved the way they were

Merging the beta into your stable conflicted in exactly three files (git recorded the resolutions with `rerere`):

| File | What happened | Resolution |
|---|---|---|
| `tests/conftest.py` | Both sides added it (add/add) | **Kept both.** Your module-level `HOME` isolation stays at the top (it must run before any app module computes its paths); the CachyOS `scripted_exec` fixture follows. |
| `app/core/settings_store.py` | Both sides added keys to the defaults dict | **Kept both:** your `disabled_managers`/`skipped_versions` plus `projects: {dirs: []}`. |
| `app/cli.py` | Both sides changed the upgrade step | **A real merge, not a pick:** the CachyOS guarded loop (skips a manager whose upgrade command cannot be built) feeding **your** `verify=by_name` call. |

`app/core/manager.py`, `app/ui/main_window.py` and `app/ui/tui.py` merged without conflict. Review `main_window.py` anyway: a clean
merge is not a correct merge.

## 5. A bug found at the seam, and fixed in the candidate

Your stable's confirm-commands dialog (`start_batch_upgrade`) built every queued upgrade command in one unguarded list comprehension:
`commands = [mgr.get_upgrade_command(pkgs) for mgr, pkgs in self.upgrade_queue]`. A manager that **cannot** build an upgrade command
raises, and one raise would break the dialog for every manager in the queue. In the stable alone nothing triggers it. With the new
drivers it can: Bundler/Gradle refuse an upgrade that spans several projects, Go refuses when nothing is installed, Deno has no upgrade path.

The candidate now builds the commands one by one, logs and records any that fail (`cannot build an upgrade command`), and still
confirms the rest. A regression test (`test_unbuildable_upgrade_command_is_reported_not_raised_and_the_rest_still_confirm`) **fails
without the fix**. The latent bug exists in `dfea6a5` itself; you may want the guard in your stable regardless of the candidate.

## 6. Tests and checks done on CachyOS (x86_64, Arch) only

| Check | Result |
|---|---|
| Your stable `dfea6a5` alone, unmodified | **226 passed**; real CLI and offscreen GUI ran clean; no errors found |
| The candidate | **330 passed** (your 226 + 103 feature tests + 1 regression test) |
| Candidate, real CLI, full `outdated` scan | exit 0 across 13 managers; Deno reported as unsupported, not failed |
| Candidate, real GUI scan (offscreen, isolated `HOME`) | scan finished, **0 error lines**, the detected-system line shows |
| Candidate, headless TUI scan | no errors; Deno skipped with an info notice |
| Verified against real tools | AUR, uv, Go, Bundler, Gradle |
| **Fixture-only, never run for real** | Snap, Nix, Distrobox, Homebrew, Conda, Bun (none installed on CachyOS) |
| **Anything on aarch64 / Fedora** | **not tested at all** |

## 7. What only you can verify (the point of this review)

Run these on the M1, in a **local** copy (section 8), with the laptop's own venv:

1. `PYTHONPATH=. QT_QPA_PLATFORM=offscreen pytest -q`: expect 330 passed. Any failure is a finding.
2. `python run.py system`: must say `aarch64` / `fedora`. Anything else is a finding, not something to paper over.
3. `python run.py managers`: **AUR must be absent** (Arch-only); **Bundler and Gradle absent** until `projects add`; DNF and Flatpak present.
4. `python run.py outdated`: exit 0; DNF and Flatpak behave as on the stable (the guards sit on the path every driver uses).
5. A GUI scan: no `❌` lines for the new drivers; your settings page, tray and skip-version still work with the extra managers.
6. **Per-manager reality on ARM64**, for each new manager that exists on the laptop (check, do not install): Snap, Nix, Distrobox,
   Homebrew/Linuxbrew, Conda, Bun, Deno, Go, uv, Gradle. These parsers were written from documented output, not real runs. Highest-risk
   guesses: `nix profile list --json` shape across versions, `brew search` non-TTY output, `conda search --json` error body, `bun update -g`.
7. M1 hazards (from general knowledge, unverified for this project): 8 GB RAM (`nix search`, `conda`'s solver, Gradle's JVM can time out
   from memory pressure, not driver bugs) and 16 KB pages (a crashing prebuilt runtime is not necessarily a driver bug).
8. Record only what you verify as `arch:` / `fedora:aarch64` data. Unverified means blank. Never add x86_64 facts.

## 8. How to read it without writing anything (the three routes)

The machines cross-mount each other's home over sshfs. The mount from your side is `~/remotes/da-nvme/`; it is read-write and
`noexec`, so treat it as read-only and run nothing through it. The live folder `~/Projects/PolyGet-stable-candidate` on CachyOS is a
git worktree whose `.git` points at a path that exists only there: **do not use it.** Use the review copy:

`~/remotes/da-nvme/Projects/_review/CachyOS-stable-candidate-latest/` (always the newest export; a plain, read-only copy: no `.git`, no venv, no governance files)

- **A. Read the diff:** `candidate-vs-master.patch` and `diffstat.txt` in that folder.
- **B. Get the real commit:** `git --no-optional-locks fetch /home/daripper/remotes/da-nvme/Projects/PolyGet CachyOS/stable-candidate:refs/remotes/cachy/stable-candidate`
  reads the CachyOS repo and writes only to your own `.git`.
- **C. Run the tests:** `rsync -a ~/remotes/da-nvme/Projects/_review/CachyOS-stable-candidate-latest/files/ ~/Projects/_review-local/candidate/`
  (reads the mount, writes locally), then use your own venv there.

The export is rebuilt by `scripts/review-export.sh` on the CachyOS beta whenever the candidate changes; the `-latest` link moves with it.

## 9. Two things you may notice, and one thing to settle

- **The `BRANCHING.md` you pushed has moved past the file the user hand-delivered.** That file (the new-manager rule plus a pointer to
  `ASAHI.md`) hashed to `0d2d96d9…` and matched your `60a2b8a`; I verified that. Your `9b82358` changed it again (`e9945a2d…`). The CachyOS
  copy has **not** been edited. Measured: replacing the CachyOS copy with yours loses only 3 lines, the old ask-before-probing rule your new
  rule deliberately supersedes; it adds no headings. So when the betas meet, **taking your file wholesale is safe**.
- **The `AGENTS.md` pointer block is byte-identical on both sides** (verified against `9b82358`), so it merges cleanly.
- **Settle:** the candidate is a *proposal for `master`*, not a promotion. Under the co-owner rules a promotion needs the user's explicit
  approval and a clean `repo-check`. The CachyOS side has no authority to push it to `master` and will not.

## 10. Everything the CachyOS agent did on your machine (for your audit)

- Read-only ssh commands: `git --no-optional-locks` status/log/rev-parse/diff/branch, `ls`, `findmnt`, `sha256sum`, and `git ls-remote`
  of the CachyOS repo through your mount of it.
- A **read-only `rsync`** of your working tree into `~/Projects/_devices/asahi/` on the CachyOS machine (first when it held 27 uncommitted
  entries, refreshed when it was committed). `.git`, venvs, caches and secrets are excluded.
- **Two writes on your machine, both temporary:** (1) while measuring the mount I ran a one-off `ssh` *from* your laptop *to* the desktop
  (`UserKnownHostsFile=/dev/null`, so `known_hosts` was not touched); (2) I created one `mktemp -d` directory under your `/tmp` to run
  `git apply --check`, and removed it. Under your newer rule (`9b82358`) I will not do (2) again; such checks run on the CachyOS side.
- Nothing was committed, pushed, installed, or edited on your machine.

## 11. Honest limits of this report
Nothing here has been run on aarch64 or Fedora. Six drivers are fixture-verified only. The branch table is a snapshot of 2026-10-17;
re-run `scripts/repo-check.sh --peer da-nvme` (or just `git ls-remote origin`) before relying on it. The CachyOS beta and this candidate
will keep changing; the numbers above describe commit `dbd1fbc`.
