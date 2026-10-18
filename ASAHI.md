# Asahi rules (this laptop's agents)

Machine-specific rules for agents on the Asahi laptop. The shared model is in `BRANCHING.md`; this file
adapts it for this machine and how it applies the shared `master` rules. Where the two disagree, ask the user.

## This machine (verified 2026-10-17)

| Fact | Value |
|---|---|
| Hardware | Apple MacBook Air (M1, 2020), tailnet `asahi` |
| CPU / page size | `aarch64`, **16 KB pages** (`getconf PAGESIZE` = 16384) |
| RAM | 7.3 GiB usable (8 GB model); usually under pressure |
| OS | `ID=fedora-asahi-remix`, `ID_LIKE=fedora`, Fedora 44 (PolyGet maps it to the `fedora` family) |
| Repo | `~/Projects/PolyGet` |

Until the CachyOS branch is merged, `python run.py system` does not exist on this branch: identify the
machine with `uname -m` and `/etc/os-release`. If it isn't `aarch64` + Fedora, stop and ask the user.

## Branches

- **`master` is the stable line, co-owned by both machines** (`BRANCHING.md`, "Who owns what"). Stable
  baseline adopted by the user on 2026-10-17: `dfea6a5`. It follows the co-owner rules only; there is no
  separate freeze.
- **`Asahi/BETA-FEATURES` is owned by this laptop** and is where agents build here. Commit to it, never
  directly to `master`.
- `CachyOS/BETA-FEATURES` is owned by the desktop. Read it (`git fetch`, `git show`, a worktree); never
  commit to it or push it from here.

## Reviewing and promoting `master` from this laptop

- **Start of every session:** check this clone against GitHub and the desktop: local `master` vs
  `origin/master`, the beta behind `origin/master`, unpushed or uncommitted work, diverged branches.
  `scripts/repo-check.sh` (with `--peer da-nvme`) does this once the CachyOS branch is merged; until then
  do it by hand with `git fetch`, `git status`, and `git log` on both sides of each branch. A beta that
  matches its remote while local `master` doesn't match `origin/master` is an alert: stop and tell the user.
- **Promoting** (merge from a beta into `master`) and **pushing `master`** each need the user's explicit
  approval, every time, plus a clean `repo-check.sh --promoting --peer da-nvme` and the `BRANCHING.md`
  checklist: tests green on **both** machines, real-tool runs, clean degradation on the other distro,
  shared files merged deliberately. Fast-forward or merge only, never force. Tell the user to let the
  desktop know `master` moved.
- Pushing the beta and opening PRs also need the user's approval each time.
- The `pre-push` guard is optional here (not installed). Install it only if the user asks.
- Merges, not rebases, for anything already pushed.

## Managers

Follow "new managers on sync" in `BRANCHING.md`: check this system and its projects yourself, report only
managers actually found, and ask the user whether to ignore, install, or add each one.

## Architecture: aarch64 facts only

- Record only what you verified on this M1 (`arch:` lists, `fedora:aarch64` install keys once the CachyOS
  architecture work is merged). Never add x86_64 facts; CachyOS owns those. Unverified means blank.
- Handle differences with detection and data, never per-architecture copies of code.
- Tests fake the architecture so they pass on both CPUs.
- M1 hazards to rule out before blaming a driver: a timeout may be memory pressure (nix search, conda's
  solver, Gradle's JVM, PySide6 installs); a startup crash may be a binary built for 4 KB pages.

## Sharing with CachyOS

`BRANCHING.md`'s sharing rules apply as-is: the other machine's repo is only ever read, never synced into
a working repo, and the "never sync" list (`.git/`, `.venv/`, user config, keys) holds.

**The desktop's whole home is mounted here at `/home/daripper/remotes/da-nvme/`** (sshfs over Tailscale,
works off the home network). Its repo is `/home/daripper/remotes/da-nvme/Projects/PolyGet`. Read and review
anything there. The mount is read-write, but treat it as read-only: never write, edit, delete, or run
anything through it, and use `git --no-optional-locks` there so git leaves no lock or index changes. If the
mount is empty or stale, ssh to `da-nvme` instead of remounting it yourself.
