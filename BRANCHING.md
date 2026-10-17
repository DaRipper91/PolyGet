# Branching

PolyGet is **one project**, released as **one version** that runs on any system. There are no
per-OS forks. Two machines develop it, each for its own distro family, and both feed one stable line.

| Branch | Lives on | Purpose |
|---|---|---|
| `master` | GitHub; **co-owned by both machines** | **Stable.** Only code built, tested, and proven on **both** Asahi and CachyOS. |
| `CachyOS/BETA-FEATURES` | CachyOS desktop (Arch) | Stable plus changes worked on and tested only on this machine. |
| `Asahi/BETA-FEATURES` | Asahi laptop (Fedora) | Same idea from the Fedora side. |

Both betas are built against stable and merge into `master` once proven on the other machine.
Neither beta overwrites `master`, and neither overwrites the other.

## Who owns what

- **`master` is co-owned.** Either machine may advance it, but only by following "Promoting a beta change to `master`" below,
  by fast-forward or merge, never by force, and only after `scripts/repo-check.sh --promoting --peer <other machine>` is clean.
  Tell the other machine afterwards; its next repo check will show that `master` moved.
- **Each beta branch has exactly one owner.** `CachyOS/BETA-FEATURES` is written only from the CachyOS desktop and
  `Asahi/BETA-FEATURES` only from the Asahi laptop. Read the other machine's beta freely; never write to it.

## Start of every session, and before any promotion: run the repo check

```bash
scripts/repo-check.sh                 # this clone against GitHub
scripts/repo-check.sh --peer asahi    # ...and the other machine, read-only over ssh (use da-nvme from Asahi)
scripts/repo-check.sh --promoting     # right before pushing master (a local master AHEAD of origin is then expected)
```

Exit status: **0** clean · **1** warnings, a repo review is suggested · **2** alert, do not merge into or push `master` until the
repo has been reviewed. The case it exists for: **a beta that matches its remote while local `master` does not match
`origin/master`.** That means the stable line moved somewhere this clone cannot see, and a green beta hides it. Other things it
flags: a beta behind `origin/master`, unpushed commits, uncommitted work, a diverged branch, and (with `--peer`) the other machine
having commits or uncommitted work that GitHub does not.

## Either machine's working copy can be ahead of GitHub

Most development happens on Asahi, so its working copy (committed or not) can be **ahead of GitHub's `master`**.
Treat GitHub's `master` as possibly stale until that work is pushed. When `CachyOS/BETA-FEATURES` was
created, `master` was at `ad511b1`.

**Before merging or promoting anything:**
1. On the other machine, check for unpushed or uncommitted work (`git status`, `git log origin/master..`, or
   `scripts/repo-check.sh --peer <other>` from here) and push it, so GitHub's `master` is the real stable line.
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

## Which machine am I? (identity comes from the system, not from a file)

Run `python run.py system` and match it before writing a report or pushing:

| `system` says | Machine | Owns / pushes to |
|---|---|---|
| `x86_64` + `arch` | CachyOS desktop (tailnet `da-nvme`) | `CachyOS/*` freely; `master` only by the promotion steps |
| `aarch64` + `fedora` | Asahi laptop, Apple M1 (tailnet `asahi`) | `Asahi/*` freely; `master` only by the promotion steps |

If what you are on does not match the branch you are about to write to, **stop and ask the user.**

## Sharing the repo between the machines (Tailscale + ssh/rsync)

Both machines can reach each other with plain ssh over Tailscale. That lets either one read the other's real checkout,
uncommitted work included. **The other machine's repo is only ever read; never sync into a working repo.**

- `scripts/peer-snapshot.sh --git [peer]`: fetch the peer's *committed* branches as `peer-<name>/*`.
- `scripts/peer-snapshot.sh --go [peer]`: rsync its working tree into `~/Projects/_devices/<peer>/PolyGet`, read-only.
  Dry run is the default. On Asahi use the peer name `da-nvme`.
- **Never sync:** `.git/`, `.venv/` and caches (x86_64 vs aarch64), `.git/hooks` and `.git/info/attributes`, git config,
  `~/.config/polyget/`, keyrings, ssh keys, `.env*`/`*.pem`/`*.key`. Never `rsync --delete` into a working repo.
- Do not edit or run anything under `_devices/`.
- `scripts/setup-machine.sh` (once per clone) makes merges keep each machine's own `AGENT_REPORT.md`.

## `AGENTS.md` carries a pointer here

`AGENTS.md` ends with a marked block (`polyget:multi-machine`) that sends every agent to this file. It must be
**byte-identical on both machines**: identical edits merge cleanly, a changed character conflicts. Change the wording on both
machines or neither. `AGENTS.md` is protected: edit it only when the user asks.

## Shared rules vs. per-machine rules

The model, the driver contracts, the sharing rules, and the `AGENTS.md` pointer are shared and stay identical. Each machine adapts
the rest for itself: its identity row, whether it installs the optional `pre-push` guard, the architecture facts it verifies on its own hardware, and how it applies
the shared promotion rules to its own workflow.

## For agents: new managers on sync

Whenever you review or sync a branch, diff `app/core/drivers/` and `app/core/data/manager_catalog.yaml`
for **new managers**. List each one to the user and **ask** whether to (a) check the system for it or
(b) install it, or neither. Do not probe or install before they answer, and never invent an install
command. Review the actual code and run the tests rather than trusting any report.

## For agents: the two machines differ in CPU architecture

CachyOS is **x86_64**, Asahi is **aarch64**. A green test run on one says nothing about the other.
`master` detects the distro family (`app/core/distro.py`) but **not the CPU architecture**; `CachyOS/BETA-FEATURES` adds
`app/core/arch.py`, a `system` command, and an `arch:` field plus arch-qualified install keys in the catalog. PolyGet must detect,
expose, and handle the machine architecture. Check real tool availability on the machine instead of guessing which tools have ARM64
builds, add only facts you verified on your own hardware, and use tests that fake the architecture. Details: section 14 of
`docs/reports/ASAHI-READ-ONCE-2026-10-16.md`.

## Guarding `master` (optional speed bump, on either machine)

`master` is co-owned, so pushing it is allowed, but it should be deliberate. `scripts/git-hooks/pre-push` makes it so. Hooks are not
versioned, so install it per clone on any machine that wants it:

```bash
cp scripts/git-hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

- Without an override, a push to `master` is refused and the hook explains the steps.
- A deliberate push: `git -c polyget.allowMasterPush=true push origin master`. The override still runs
  `scripts/repo-check.sh --promoting` and **refuses on an ALERT**.
- The hook **fails closed**: if `scripts/repo-check.sh` is not in the checkout (for example `master` predates it), the push is
  refused rather than silently unchecked. Push with `--no-verify` only if you accept that risk.
- Git itself already refuses an ordinary non-fast-forward push before any hook runs. The hook's check matters most for **forced**
  pushes, which skip that protection.
- A server-side rule (GitHub branch protection requiring a PR for `master`) is the only guard that also covers accidents from other
  tools. It is a setting on the remote and has not been enabled.
