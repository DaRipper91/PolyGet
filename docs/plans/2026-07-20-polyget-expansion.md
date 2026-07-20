# PolyGet: Expansion Ideas — 2026-07-20

> This is a brainstorm, not a backlog. None of this is prioritized against the fix-plan — pick
> what excites you, ignore the rest, and treat every idea below as a starting pitch, not a spec.

**Context:** PolyGet is a dual-UI (PySide6 GUI + Textual TUI) Linux package manager unifier: 15
auto-registering drivers (System/Universal/Language-Dev categories) sit behind one `PackageManager`
base contract, a catalog shows managers you don't have installed yet, and a strict-parsing
`BlueprintManager` lets you export/re-import your installed-package state as YAML across machines.
The angle these ideas take is: lean into the three structural bets this codebase has already made
— (1) the driver-registry pattern that makes "any manager can plug in" structurally true rather
than aspirational, (2) blueprints as a genuine cross-machine artifact (this developer's own daily
drivers are two different real machines — a Fedora/Asahi box and a CachyOS/Arch box — per
CLAUDE.md), and (3) the catalog's "visible even if uninstalled" principle — and ask what each of
those seams could carry that they don't carry today.

---

## Weekend-scale

### Blueprint Diff & Merge
**Pitch:** Right now a blueprint is write-only in spirit: you export machine A's state, and later
re-import it to *replicate* it somewhere else. This idea adds a side-by-side diff view: load two
blueprint YAML files (e.g. today's export from the Asahi box next to last week's CachyOS export)
and see three columns — "only here," "only there," "on both, different manager." Each row gets a
one-click "install this here" action that routes straight into the existing blueprint-install
queue. It turns blueprints from a one-directional snapshot format into something you'd actually
open on purpose to answer "what's different between my two machines right now?"
**Why this project, specifically:** `BlueprintManager.parse_blueprint()` (Strength S3) already does
the hard, boring, correct part — strict, type-checked, `safe_load`-based YAML parsing that
degrades safely on anything malformed — which is exactly the primitive a two-file diff needs and
already trusts. The two-real-machines setup in CLAUDE.md means this isn't a hypothetical
multi-device use case invented for the pitch; it's the literal daily workflow this repo is built
around, just never surfaced as a comparison tool.
**What it'd take:** one new diff module (e.g. `app/core/blueprint_diff.py`, pure dict-set logic
over two already-parsed blueprints) plus one new dialog/tab in both the GUI and TUI that reuses
the existing blueprint-install queue machinery. No new dependency.

### First Boot Wizard
**Pitch:** On a fresh install (no prior scan, no blueprint on disk), instead of dropping the user
straight into an empty dashboard, PolyGet detects the distro family and walks them through "here's
what's on this system already, here's what's catalog-visible but missing" as a guided checklist —
turning the very first launch into a five-minute "get your machine's manager stack where you want
it" flow rather than a cold, empty scan screen.
**Why this project, specifically:** This is a thin, new UI layer over two things that already
exist and already do exactly this work individually — `distro.py`'s family detection and
`catalog.py`'s "installed vs. catalog-only" split — the wizard's entire job is sequencing what's
already computed into an onboarding narrative instead of a passive store tab you have to think to
visit.
**What it'd take:** one new first-run dialog (GUI) / initial screen (TUI), a small on-disk
"first run complete" marker, no new backend logic — it's pure UI orchestration of `distro.py` +
`catalog.py` output that already exists.

---

## Subsystem-scale

### Cross-Manager Resolver
**Pitch:** Search for `ripgrep` today and you get a flat list of hits tagged by source manager with
no relationship between them — DNF's `ripgrep`, Cargo's `ripgrep`, and Flatpak's
`org.ripgrep.something` (if it existed) show up as three unrelated rows with a count breakdown at
the top. This idea adds a resolver layer that groups results by canonical package identity across
managers, shows one card per package with all its available backends as badges, flags when you
already have it installed via a *different* manager than the one you're about to install from
(so you don't end up with the same tool twice), and lets you pick a backend with a short "why"
(e.g. "Flatpak: sandboxed, slower startup" vs. "DNF: native, no sandbox").
**Why this project, specifically:** Verified directly against the code: `SearchWorker` already
fans a query out across every registered manager concurrently via `asyncio.gather` and tags each
result with `source`, but `handle_store_results()` just clears the list and repopulates it flatly
with a per-source count breakdown — there is no grouping, dedup, or cross-manager awareness at all
today. The fan-out plumbing this needs already exists; only the aggregation/ranking layer on top
of it doesn't.
**What it'd take:** a new `app/core/resolver.py` module (name-normalization + grouping over the
existing `search_packages()` results, cross-checked against each manager's already-existing
`list_installed()`), plus reworking `handle_store_results()`/the TUI's equivalent store view to
render grouped cards instead of a flat list.

### Operation Journal & Rollback
**Pitch:** Every batch upgrade currently either succeeds, partially fails (now correctly surfaced
per the `6b831c0` fix), or doesn't — but once it's done, it's done; there's no record of what
version you were on before, and no way back except manually re-pinning a version by hand. This
idea adds a persistent, append-only operation ledger that snapshots each package's pre-upgrade
version before every batch run, and — for the subset of drivers whose backend genuinely supports
it (DNF's transaction history, Pacman's package cache, APT's package cache, Cargo's `--version`
pinning) — a "Rollback last upgrade" action that reverses exactly the packages that ledger entry
touched.
**Why this project, specifically:** `SubprocessCoordinator` (Strength S2) already tracks every
spawned privileged subprocess precisely enough to layer a ledger on top of it with almost no new
plumbing, and the driver base contract (confirmed interface-consistent across all 15 drivers by
this audit's own stage 03) makes it straightforward to add one new *optional* method
(`get_downgrade_command`) that only the capable drivers implement — exactly the same
opt-in-override pattern already used for `list_repos`/`get_sync_command`. This is a meaningfully
bigger bet than the roadmap's existing one-line "update history log" item: that's a passive record,
this is an actionable one.
**What it'd take:** a new `app/core/journal.py` (JSONL-backed ledger under
`~/.local/share/polyget/`), one new optional driver method implemented by 3-4 drivers, and one new
"Rollback" action wired into the existing upgrade-queue UI.

### Supply-Chain Trust Dashboard
**Pitch:** Replace "outdated: yes/no" as the only signal in the Updates view with a per-package
risk picture: known CVEs (via each ecosystem's native audit tool where one exists), how far behind
current the installed version is, and — for Flatpak specifically — whether the app ships from a
verified/official remote or a third-party one. Packages get a badge, not just a version string, and
the dashboard can be sorted by risk instead of just alphabetically or by staleness.
**Why this project, specifically:** The roadmap already gestures at "surface npm audit/cargo audit
data" as a single checklist line, but the codebase's own driver-contract discipline (every driver
returns the same shaped dicts, confirmed with zero drift across all 15 in this audit's stage 03)
means this is naturally a first-class cross-cutting subsystem rather than a per-driver bolt-on: one
new `Finding` shape, adapters for the ecosystems that have a native audit command (`npm audit`,
`cargo audit`, `pip-audit` against Pipx's per-package venvs — which `pipx.py` already knows how to
enumerate), and a documented, honest "no data available" state for the drivers that don't (DNF/
Pacman/APT have no equivalent per-package CVE feed without a separate OS-level feed, which the
dashboard should say outright rather than silently omitting the badge).
**What it'd take:** a new `app/core/audit/` package (one adapter module per ecosystem with a native
audit tool, a shared `Finding` dataclass), and new columns/badges in the existing Updates view —
plus, if built alongside the Operation Journal above, a "risk trend over time" view for free.

---

## Swing-for-the-fence

### PolyGet Fleet
**Pitch:** Turn PolyGet from a single-machine desktop tool into a small client/server system: a
lightweight local daemon exposes the exact same `app.core` driver layer over a Unix-socket (or
loopback-only) JSON-RPC API, and the existing GUI/TUI gain a "remote machine" concept — add a
second machine (reachable over SSH or Tailscale-style overlay), and the dashboard now shows *both*
machines' outdated-package lists side by side, with blueprint sync becoming a live, bidirectional
push/pull between them instead of a manual export-file-then-import dance.
**Why this project, specifically:** This isn't an invented multi-device scenario — CLAUDE.md states
outright that this developer's actual daily-driver test environment *is* two real, different
machines (Fedora/Asahi and CachyOS/Arch). Every architectural piece needed already exists in
isolated form: the driver registry is already a clean, serializable "what can this machine do"
surface; blueprints are already a portable, safely-parsed wire format; `SubprocessCoordinator`
already isolates process lifecycle from UI lifecycle. Fleet mode is the natural end-state of
"blueprints let you replicate state across machines," just made live instead of file-based.
**What it'd take:** a genuinely new codebase-within-the-codebase — a daemon entry point (e.g.
`app/daemon/`), a minimal wire protocol/schema for driver results, an SSH-tunnel or loopback-bind
transport, and a "remote manager" abstraction in the UI layer that looks like a local
`PackageManager` to existing code but proxies over the wire. Likely needs at least one new
dependency (an RPC/serialization library, or hand-rolled JSON-over-socket).

### User-Authorable Driver Plugins
**Pitch:** Right now, covering one of the 15 catalog-only-no-driver managers (zypper, apk, xbps,
nix, snap, portage, guix, composer, go, nuget, maven, luarocks, bundler, gradle, eopkg, distrobox)
means writing a PR into this repo. This idea opens that seam up: PolyGet loads additional drivers
from `~/.config/polyget/drivers/*.py` (or, for the common case of "just wrap a CLI tool," a
declarative YAML spec requiring no Python at all — command templates for check/list/install/
upgrade, no code), validated against the same six-method contract this audit's stage 03 confirmed
is honored identically across all 15 built-in drivers, plus a `polyget driver init <name>` scaffold
generator and a conformance test harness a plugin author can run against their own driver before
ever touching the main dashboard.
**Why this project, specifically:** This is the direct, load-bearing extension of Strength S1 — the
driver registry is *already* structurally incapable of silently mis-registering a driver
(`pkgutil.iter_modules` + a decorator, no manual dispatch table to forget to update). That property
is exactly what makes it safe to point at a second, user-controlled directory instead of just the
one shipped in the repo: the mechanism that currently guarantees "every driver file in `app/core/
drivers/` is correctly wired up" generalizes to "every driver file anywhere on this trust boundary
is correctly wired up," with no new failure mode introduced. It also directly operationalizes
CLAUDE.md's "a manager you don't have installed should still be visible" principle one step
further: even a manager *this project's own maintainer never wrote a driver for* can become fully
first-class.
**What it'd take:** an external-plugin-directory loader (`app/core/drivers/external.py` alongside
the existing `pkgutil` loader), a YAML-driven "generic CLI driver" implementation of the
`PackageManager` contract for the no-code case, a scaffold/validation CLI, and a documented trust
boundary (this is deliberately *not* sandboxed — plugin code runs with the same privileges as
PolyGet itself, which needs to be stated plainly rather than implied).

---

## Ideas we deliberately left out

- A generic "plugin marketplace with ratings/discovery UI" on top of the plugin-loader idea above —
  cut for being the kind of thing that could bolt onto literally any extensible app (VS Code,
  Obsidian, etc.) and isn't grounded in anything specific this repo already does; the plugin-loading
  mechanism itself earned its place because it's a direct extension of the registry pattern, but a
  marketplace UI on top of it is generic scope-creep, not a PolyGet-specific idea.
- "Add scheduling/cron for automatic scans" — this is really just the roadmap's already-listed
  "system tray + background scan" item at a slightly different angle; it's real and worth doing,
  but it's enhancement-shaped (a mode toggle on an existing feature), not expansion-shaped, so it's
  explicitly left for the fix-plan/roadmap rather than restated here.
