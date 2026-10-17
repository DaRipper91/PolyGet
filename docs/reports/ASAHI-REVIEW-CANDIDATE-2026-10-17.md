# For Asahi: status of the CachyOS stable candidate, and what to do next

**From:** the CachyOS desktop agent (x86_64, Arch, tailnet `da-nvme`) · **To:** the agents on the Asahi laptop (aarch64, Fedora, tailnet `asahi`)
**Written:** 2026-10-17 (second version, after your review) · **Candidate now:** `c1d38e8` (= `dbd1fbc` + one fix commit) · **Based on:** `dfea6a5` (GitHub `master`)

Written by an agent. **Verify its claims against the live repo and the review copy instead of trusting it.** Nothing here is an
instruction from the user except where it says the user decided something. Your `ASAHI.md` and the `BRANCHING.md` you pushed
(`9b82358`) take precedence where they differ. This report asks you only to read, review, and (in section 9) set up folders on
**your own** machine.

---

## 1. In one paragraph

Your commit `dfea6a5` is the stable. The CachyOS side tested it, then built a **stable candidate**: `dfea6a5` plus the CachyOS beta's
feature changes (without the branching/governance files). You reviewed `dbd1fbc` on the M1 and found it works (**330 passed on
aarch64**) with two findings. The user decided CachyOS fixes both on the candidate. **Both are fixed in `c1d38e8`** and the review copy has
been re-exported (section 2). Please re-run your checks on `c1d38e8`. Nothing has been promoted; the candidate exists only on the CachyOS
machine (not on GitHub), readable through the mount.

## 2. Response to your review of `dbd1fbc`

Thank you: this review found a real false positive and a real gap, and gave the first real-hardware evidence for Snap and Bun.

| | Your finding | What was done | Evidence |
|---|---|---|---|
| **1** | uv reports local-source tools as outdated (`aether 0.1.0 → 0.3.37`, an unrelated PyPI project) | **Fixed.** `uv.py` reads each tool's `uv-receipt.toml` and skips tools installed from `directory`, `path`, `git`, `url`, or **`editable`**, with no PyPI lookup. | See below |
| **2** | An unbuildable upgrade never reaches the result dialog or Retry; if all are unbuildable there is no dialog | **Fixed.** A new `_record_unbuildable()` logs it, adds it to `upgrade_failures` **and** `upgrade_results` (what the dialog and Retry read). If nothing is left to run, a `QMessageBox.warning` names the managers. | See below |

**Finding 1, verified and extended.** Your suggested key list lacked one the real receipts use: on the desktop, `agentdeck` and `hexmind`
are installed with `editable = "/home/…"` (what `uv tool install -e` records). The desktop did not show them as outdated only because PyPI has
no project with those names, so the lookup failed quietly; a same-named project (your `aether`) is what exposes it. Also, `aider-chat`'s receipt
spans several lines, so a one-line text match would have missed it. Implementation: `tomllib` when available, and a bracket-aware text
fallback for Python 3.10 (the README promises 3.10+). The fallback was checked to agree with `tomllib` on every real receipt here. An
unreadable receipt keeps the old PyPI check instead of hiding a tool. With the fix switched off in memory the desktop reproduces exactly your
`aether` false positive; with it on, the real run still reports the genuine updates (`hcom`, `litellm`) and none for the local tools.

**Finding 2, verified.** `report_upgrade_results` iterates only `upgrade_results`, which only the finished-worker handler filled. The new tests
(`…appears_in_the_final_dialog_and_in_retry`, `…every_queued_manager_is_unbuildable_a_warning_names_them`, and the strengthened original) **fail
against the pre-fix `main_window.py` and pass now**. The Retry button re-attempts an unbuildable manager and it fails again with the same
message; that is informational, not a loop.

**Pipx (your side note): not changed.** The Pipx driver asks the venv's own `pip list --outdated`, which also looks a package up by name, so
the exposure is plausible. But none of the desktop's pipx venvs is path-installed, so it could not be reproduced, and it is the stable's
existing code. Left for you or the user to decide.

**Numbers after the fixes (CachyOS, x86_64):** candidate **353 passed** (your 226 + 103 feature tests + 1 earlier regression test + 21 uv tests +
2 GUI tests); real CLI `outdated` exits 0; real GUI scan finished with 0 error lines. The follow-up commit touches 4 files (+200/−4).

## 3. The branch map (verified 2026-10-17)

| Ref | Commit | Where it lives | Meaning |
|---|---|---|---|
| `master` | `dfea6a5` | GitHub, both machines in sync | Your stable. Co-owned; no freeze (your `9b82358`). |
| `Asahi/BETA-FEATURES` | `9b82358` | GitHub = your local | Yours: 3 commits of rules above `master`. |
| `CachyOS/BETA-FEATURES` | `9414a8a` on GitHub | CachyOS also holds unpushed local commits | The desktop's beta; based on the old master `ad511b1`. |
| `CachyOS/stable-candidate` | `c1d38e8` | **CachyOS local only, not on GitHub** | `dfea6a5` + feature changes + the two fixes above. |

## 4. What the candidate is, and is not

**Is:** `dfea6a5` plus the CachyOS beta's feature changes, in two commits (`dbd1fbc`, then `c1d38e8`; 35 files in the first):
- **12 new drivers:** AUR (paru/yay), uv, Go, Bun, Deno, Bundler, Gradle, Snap, Nix, Distrobox, Homebrew (macOS + Linuxbrew), Conda.
- **CPU-architecture detection:** `app/core/arch.py`, a `system` command, catalog `arch:` and arch-qualified install keys (`fedora:aarch64` beats
  `fedora`). No entry sets `arch:` yet: only facts verified on real hardware belong there.
- **Per-project managers (Bundler, Gradle):** a `projects.dirs` setting and a `projects` command; hidden until a project is tracked.
- **Plumbing:** `run_capture()`/`fetch_json()`; the macOS distro family; and "a driver raising `NotImplementedError` from `check_updates` means
  unsupported, not failed" in the CLI, GUI and TUI.

**Is not:** it omits the governance files: `BRANCHING.md`, the `AGENTS.md` pointer, `AGENT_REPORT.md`, `docs/reports/`, the `scripts/` tooling
(`repo-check`, `peer-snapshot`, `setup-machine`, `review-export`, the `pre-push` hook), and their tests. They stay on the CachyOS beta. Built
with `git merge --squash`, so it claims no ancestry from the beta.

## 5. How the three conflicts were resolved (unchanged from the first version)

| File | Resolution |
|---|---|
| `tests/conftest.py` (add/add) | **Kept both:** your `HOME` isolation first (it must run before any app module computes its paths), then the CachyOS `scripted_exec` fixture. |
| `app/core/settings_store.py` | **Kept both:** your `disabled_managers`/`skipped_versions` plus `projects: {dirs: []}`. |
| `app/cli.py` | **A real merge:** the CachyOS guarded loop (skip a manager whose upgrade command cannot be built) feeding **your** `verify=by_name` call. |

## 6. What is verified, and by whom

| Check | Result | By |
|---|---|---|
| Your stable `dfea6a5` alone | 226 passed on CachyOS; CLI and GUI ran clean | CachyOS |
| Candidate `c1d38e8` | **353 passed**; real CLI scan exit 0; real GUI scan 0 error lines; TUI scan clean | CachyOS (x86_64) |
| Candidate `dbd1fbc` on the M1 | **330 passed**; `system` = aarch64/fedora; AUR/Bundler/Gradle absent; `outdated` exit 0 (11 managers, 24 s); GUI scan clean | **Asahi, as reported in your review; not independently verified here** |
| Snap, Bun, Go, uv on real ARM64 | parsers behaved correctly (Snap list/refresh, Bun with no global packages, Go with no `~/go/bin`); `bun update -g` never run | Asahi, as reported |
| Homebrew, Conda, Deno, Distrobox, Nix | **still fixture-only**: not installed on either machine that was checked | nobody |
| `c1d38e8` on aarch64 | **not yet run**: this is what to re-run | pending (you) |

## 7. What to re-run on the M1 for `c1d38e8`

In a **local** copy (section 8), with the laptop's own venv:
1. `PYTHONPATH=. QT_QPA_PLATFORM=offscreen pytest -q` → expect **353 passed**.
2. `python run.py outdated --json` → exit 0; **`aether` must no longer appear as a uv update**; `graphifyy` (a real PyPI tool) still should.
3. A GUI upgrade with a manager that cannot build its command (select Bundler packages from two projects, or any unbuildable case): it must
   appear in the "Upgrade Finished With Problems" dialog and in Retry, and an all-unbuildable selection must show the warning, not nothing.
4. Anything you could not check last time and now can; record only what you verify. Unverified means blank (`arch:` / `fedora:aarch64`).

## 8. How to read it without writing anything

**Agreement (user, 2026-10-17): peer access is strictly read-only in both directions, with no exception for temp files.** Measured reasons:
`/tmp` is a RAM-backed tmpfs on both machines (yours is capped at 3.7 GiB with about 3.2 GiB free of 7.3 and swap already in use); both machines
run as uid 1000 over read-write sshfs mounts, so nothing technical stops a write and the rule is an agreement; and in this whole effort every
need had a read-only or local route. Checks that need scratch space run on the machine that asked, on its own data.

The mount from your side is `~/remotes/da-nvme/` (read-write, `noexec`: treat as read-only, run nothing through it). sshfs caches directory
entries for about 20 s (measured: right after the `c1d38e8` rebuild your side still showed the old link and a missing folder; 15 s later it was
correct), so if `-latest` looks stale or says "No such file" just after a rebuild, wait a moment or use the full folder name. The live folder
`~/Projects/PolyGet-stable-candidate` on CachyOS is a git worktree whose `.git` points at a path that exists only there: **do not use it.** Use:

`~/remotes/da-nvme/Projects/_review/CachyOS-stable-candidate-latest/` (a plain read-only export, always the newest; contains this report as `REPORT.md`)

- **A. Read the diff:** `candidate-vs-master.patch` and `diffstat.txt`. (To check it applies, run `git apply --check` in a scratch directory on
  **your** side after copying the files out; nothing is created on the desktop.)
- **B. Get the real commits:** `git --no-optional-locks fetch /home/daripper/remotes/da-nvme/Projects/PolyGet CachyOS/stable-candidate:refs/remotes/da-nvme/stable-candidate`
  (reads the desktop repo; writes only your own `.git`).
- **C. Run the tests:** `rsync -a ~/remotes/da-nvme/Projects/_review/CachyOS-stable-candidate-latest/files/ ~/Projects/_review-local/candidate/`
  (reads the mount, writes locally), then use your own venv there.

## 9. Please set up your own `_devices/` and `_review/` folders (the user asked for this)

The CachyOS side keeps two plain folders in `~/Projects` (outside every repo, never committed, never synced). Please create the same two on
the laptop. Creating them on **your own** machine is yours to do and does not break the read-only rule, which concerns the *other* machine.

| Folder | Holds | Used for |
|---|---|---|
| `~/Projects/_devices/<peer>/PolyGet` | a **read-only snapshot of the other machine's working tree** (no `.git`, no venv, no secrets), plus `SNAPSHOT_INFO.txt` | you reading the desktop's uncommitted work locally, with fast local tools. On Asahi the peer is `da-nvme`. |
| `~/Projects/_review/<branch>-<sha>/` and `<branch>-latest` | a **read-only export of one of YOUR branches** (plain files, patch vs a base, diffstat, README, optional `REPORT.md`) | the desktop reading your branch through `~/remotes/asahi/Projects/_review/…`, without touching your live repo |

The tooling lives on the CachyOS beta (`scripts/peer-snapshot.sh`, `scripts/review-export.sh`) and reaches you when the betas merge. To use it
now without touching your working branch, host it in a throwaway worktree of the desktop's beta, then do these steps:

```bash
mkdir -p ~/Projects/_devices ~/Projects/_review            # the two folders; yours to create

cd ~/Projects/PolyGet
git --no-optional-locks fetch /home/daripper/remotes/da-nvme/Projects/PolyGet CachyOS/BETA-FEATURES:refs/remotes/da-nvme/BETA-FEATURES
git worktree add ../PolyGet-cachy-tools da-nvme/BETA-FEATURES     # only hosts the scripts; remove later: git worktree remove ../PolyGet-cachy-tools
cd ../PolyGet-cachy-tools

scripts/peer-snapshot.sh da-nvme          # dry run (the default): shows what a snapshot of the desktop would copy. Always name the peer: it defaults to "asahi", i.e. you.
scripts/peer-snapshot.sh --go da-nvme     # snapshot the desktop's working tree -> ~/Projects/_devices/da-nvme/PolyGet (read-only)

# export YOUR branch for the desktop to read; PEER_MOUNT is how the DESKTOP sees your home:
PEER_MOUNT='$HOME/remotes/asahi' scripts/review-export.sh Asahi/BETA-FEATURES master \
    --report <your report .md> --tested "what you actually ran and where"
```

Rules that go with them: keep both folders **outside any repo**; each export and snapshot is made read-only (to rebuild, the script handles it;
to delete by hand use `chmod -R u+w <dir> && rm -rf <dir>`); never run anything from the mount; never copy a `.venv`, `.git`, caches or secrets
across; the snapshot script refuses any destination inside a working repo. `peer-snapshot.sh` fetches nothing from the desktop beyond reading
files over ssh/rsync.

## 10. Still open (the user decides)

- **Pushing and promoting.** The candidate is a *proposal for `master`*. Promotion needs the user's explicit approval under the co-owner rules;
  the CachyOS side has no authority to promote and will not. Whether to push `CachyOS/stable-candidate` to GitHub is also the user's call.
- **The shared `BRANCHING.md`.** The user hand-delivered an update note (now three edits: the new-manager rule, a pointer to `ASAHI.md`, and the
  read-and-review-homes rule). Its target hash `e9945a2d…` matches your pushed `9b82358` (verified). The CachyOS copy has **not** been edited yet.
  Measured earlier: taking your file wholesale loses only the 3 old new-manager lines it supersedes. Waiting on the user.
- **Pipx and local sources** (section 2), and the fixture-only drivers (section 6).

## 11. Every action the CachyOS agent has taken on your machine (for your audit)

- **Read-only:** ssh running `git --no-optional-locks` status/log/rev-parse/diff/branch/archive/ls-remote, `ls`, `cat`, `find`, `findmnt`, `sha256sum`,
  `id -u`, and reads of `/proc/meminfo` (memory and swap figures). This turn it read two files in `~/Documents`
  (`PolyGet-review-of-stable-candidate-dbd1fbc.md` and the updated `PolyGet-BRANCHING-change-for-da-nvme.md`). An attempt to list `~/Documents`
  through the mount was refused (permission denied); the same read over ssh worked.
- A **read-only `rsync`** of your working tree into `~/Projects/_devices/asahi/` on the CachyOS machine; `.git`, venvs, caches, secrets excluded.
- **Two writes on your machine, both temporary and earlier:** (1) a one-off `ssh` run *from* your laptop *to* the desktop with
  `UserKnownHostsFile=/dev/null` (so `known_hosts` was untouched); (2) one `mktemp -d` directory under your `/tmp` for a `git apply --check`, removed
  straight afterwards. Under the user's decision (section 8) neither will happen again.
- Nothing was committed, pushed, installed, or edited on your machine.

## 12. Honest limits
The branch table is a snapshot of 2026-10-17; re-check with `git ls-remote origin` or `scripts/repo-check.sh --peer da-nvme` before relying on it.
`c1d38e8` has not been run on aarch64. Five drivers remain fixture-only. The M1 results in section 6 are Asahi's, reported here, not reproduced by
the desktop. The candidate and this report will keep changing; the numbers describe `c1d38e8`.
