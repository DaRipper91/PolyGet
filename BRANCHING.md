# Branching

PolyGet is **one project**, released as **one version** that runs on any system. There are no
per-OS forks. Two machines develop it, each for its own distro family, and both feed one stable line.

| Branch | Lives on | Purpose |
|---|---|---|
| `master` | GitHub; owned by the Asahi laptop (Fedora) | **Stable.** Only code built, tested, and proven on **both** Asahi and CachyOS. |
| `CachyOS/BETA-FEATURES` | CachyOS desktop (Arch) | Stable plus changes worked on and tested only on this machine. |
| `Asahi/BETA-FEATURES` (suggested name) | Asahi laptop (Fedora) | Same idea from the Fedora side. |

Both betas are built against stable and merge into `master` once proven on the other machine.
Neither beta overwrites `master`, and neither overwrites the other.

## Asahi usually has the newest files

Most development happens on Asahi, so the Asahi working copy can be **ahead of GitHub's `master`**.
Treat GitHub's `master` as possibly stale until Asahi has pushed. When `CachyOS/BETA-FEATURES` was
created, `master` was at `ad511b1`.

**Before merging or promoting anything:**
1. On Asahi, check for unpushed or uncommitted work (`git status`, `git log origin/master..`) and push
   it, so GitHub's `master` is the real stable line.
2. On CachyOS: `git fetch origin && git merge origin/master` into the beta branch, and resolve
   conflicts here. A merge is preferred over a rebase because it does not rewrite pushed history.
3. Re-run the tests here (`PYTHONPATH=. .venv/bin/pytest`).

## One codebase, per-distro behavior at runtime

Distro differences are handled by detection, never by forking files:
- A driver reports `is_available() == False` when its tool or platform is absent (the AUR driver is
  invisible off Arch; Homebrew skips casks off macOS).
- Install commands live in `app/core/data/manager_catalog.yaml`, keyed by distro family (`fedora`,
  `arch`, `debian`, `macos`, ...), resolved by `app/core/distro.py`.

If a change only makes sense on one distro, gate it that way and it can ship in the same version.

## Promoting a beta change to `master`

A change reaches `master` only when all of these are true:
- [ ] The test suite passes on **both** machines (`pytest` is a dev dependency, not in `requirements.txt`).
- [ ] It was exercised against the real tool on at least one machine that has it, not only fixtures.
- [ ] It degrades cleanly on the other distro (hidden or unsupported, never an error on every scan).
- [ ] Shared files are merged deliberately. Expect conflicts in `manager_catalog.yaml`,
      `app/core/manager.py`, `app/cli.py`, and `README.md`, which both betas touch.

Keep commits small and one-feature-each so they can be taken or left individually.

## For agents: new managers on sync

Whenever you review or sync a branch, diff `app/core/drivers/` and `app/core/data/manager_catalog.yaml`
for **new managers**. List each one to the user and **ask** whether to (a) check the system for it or
(b) install it, or neither. Do not probe or install before they answer, and never invent an install
command. Review the actual code and run the tests rather than trusting any report.

## Guarding `master` on beta-only machines

`scripts/git-hooks/pre-push` refuses any push to `master`. Hooks are not versioned, so install it per
clone on beta-only machines:

```bash
cp scripts/git-hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

One deliberate push: `git -c polyget.allowMasterPush=true push origin HEAD:master`.
Do **not** install it on the machine that owns the stable line. A server-side rule (GitHub branch
protection requiring a PR for `master`) is the only guard that also covers accidents from other tools.
