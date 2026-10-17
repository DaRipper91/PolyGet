# Asahi rules (this laptop's agents)

Machine-specific rules for agents on the Asahi laptop. The shared model is in `BRANCHING.md`; this file
adapts it for this machine and its governance of `master`. Where the two disagree, ask the user.

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

- **`master` is the stable line, owned by this laptop.** Stable baseline adopted by the user on 2026-10-17:
  `dfea6a5`. It is frozen: nothing new lands on it until the user has tested it on **both** this laptop and
  CachyOS and the errors found there are fixed. After that, only changes proven on both machines are
  promoted, and only when the user says so.
- **`Asahi/BETA-FEATURES` is where agents build on this laptop.** Branch from it and commit to it, never
  directly to `master`.
- `CachyOS/BETA-FEATURES` belongs to the desktop. Read it (`git fetch`, `git show`, a worktree); never
  commit to it or push it from here.

## Governance of `master`

- Promoting to `master` (merge from a beta), pushing anything, and opening PRs each need the user's
  explicit approval, every time. Approval for one does not cover the next.
- Before a promotion, the `BRANCHING.md` checklist applies: tests green on **both** machines, real-tool
  runs, clean degradation on the other distro, shared files merged deliberately.
- Do **not** install `scripts/git-hooks/pre-push` here. This laptop owns `master`; the guard is for
  beta-only machines.
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
