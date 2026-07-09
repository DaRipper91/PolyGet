# PolyGet: Expand Manager Coverage — System, Universal, and Language/Dev

> **For Antigravity:** This plan assumes the "Manager Store, Discovery Catalog, and Repos Tab" plan has already added `app/core/catalog.py` and `app/core/data/manager_catalog.yaml`. If it hasn't landed yet, do that plan first — this one extends its catalog rather than replacing it. This plan is scoped to three categories only: **System** (native OS package managers), **Universal** (sandboxed, distro-agnostic), and **Language/Dev** (per-language tooling). Toolchain/version managers (rustup, pyenv, nvm, asdf) and meta-layers that just wrap an existing manager (AUR helpers) are explicitly out of scope — they manage *which version of a tool* is active, not packages, and belong to a different feature if ever built.

**Goal:** PolyGet's catalog currently lists 5 managers with full drivers and a handful of catalog-only placeholders. This plan brings the catalog up to comprehensive coverage of the three relevant categories, and — critically — adds a **full working driver for Pacman**, since it's the native manager on the primary CachyOS desktop and currently has zero support in the project despite that.

**Architecture:** No new architecture beyond what the catalog/discovery plan already established — this is primarily content (catalog entries) plus two new full `PackageManager` driver classes for the highest-priority gaps (Pacman, RubyGems).

**Tech Stack:** Python 3, PyYAML, asyncio (unchanged)

---

### Task 1: Expand the Manager Catalog to Full Taxonomy Coverage

**Files:**
- Modify: `app/core/data/manager_catalog.yaml`
- Modify: `tests/test_catalog.py`

**Step 1: Add remaining System-category entries**
Append entries for every native OS package manager not yet in the catalog, all with `has_driver: false` except Pacman (see Task 2):
```yaml
- id: apt
  name: APT
  category: System
  description: Debian/Ubuntu system package manager.
  icon: package-x-generic
  binary: apt-get
  has_driver: false
  self_install: {}

- id: zypper
  name: Zypper
  category: System
  description: openSUSE system package manager.
  icon: package-x-generic
  binary: zypper
  has_driver: false
  self_install: {}

- id: apk
  name: APK
  category: System
  description: Alpine Linux system package manager.
  icon: package-x-generic
  binary: apk
  has_driver: false
  self_install: {}

- id: xbps
  name: XBPS
  category: System
  description: Void Linux system package manager.
  icon: package-x-generic
  binary: xbps-install
  has_driver: false
  self_install: {}

- id: portage
  name: Portage
  category: System
  description: Gentoo's source-based package manager (emerge).
  icon: package-x-generic
  binary: emerge
  has_driver: false
  self_install: {}

- id: eopkg
  name: eopkg
  category: System
  description: Solus system package manager.
  icon: package-x-generic
  binary: eopkg
  has_driver: false
  self_install: {}
```
*(`pkg` for FreeBSD is intentionally omitted — PolyGet targets Linux desktops, and Asahi/CachyOS are the two real machines this needs to run on.)*

**Step 2: Add remaining Universal-category entries**
```yaml
- id: nix
  name: Nix
  category: Universal
  description: Purely functional, reproducible package manager and profile system.
  icon: package-x-generic
  binary: nix
  has_driver: false
  self_install: {}

- id: guix
  name: Guix
  category: Universal
  description: Functional package manager in the same lineage as Nix, GNU project.
  icon: package-x-generic
  binary: guix
  has_driver: false
  self_install: {}
```
*(Snap and Flatpak were already added in the catalog/discovery plan — don't duplicate.)*

**Step 3: Add remaining Language/Dev-category entries**
```yaml
- id: gem
  name: RubyGems
  category: Language/Dev
  description: Ruby's package manager, pulls from rubygems.org.
  icon: text-x-generic
  binary: gem
  has_driver: true   # implemented in Task 3
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "ruby"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "ruby"]
    debian: ["pkexec", "apt-get", "install", "-y", "ruby-full"]

- id: composer
  name: Composer
  category: Language/Dev
  description: PHP's dependency and package manager.
  icon: text-x-generic
  binary: composer
  has_driver: false
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "composer"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "composer"]
    debian: ["pkexec", "apt-get", "install", "-y", "composer"]

- id: go
  name: Go Modules
  category: Language/Dev
  description: Go's built-in module and binary installer (go install).
  icon: text-x-generic
  binary: go
  has_driver: false
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "golang"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "go"]
    debian: ["pkexec", "apt-get", "install", "-y", "golang-go"]

- id: nuget
  name: NuGet
  category: Language/Dev
  description: .NET/C# package manager.
  icon: text-x-generic
  binary: dotnet
  has_driver: false
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "dotnet-sdk-8.0"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "dotnet-sdk"]
    debian: ["pkexec", "apt-get", "install", "-y", "dotnet-sdk-8.0"]

- id: maven
  name: Maven
  category: Language/Dev
  description: Java build and dependency manager.
  icon: text-x-generic
  binary: mvn
  has_driver: false
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "maven"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "maven"]
    debian: ["pkexec", "apt-get", "install", "-y", "maven"]

- id: luarocks
  name: LuaRocks
  category: Language/Dev
  description: Lua's package manager.
  icon: text-x-generic
  binary: luarocks
  has_driver: false
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "luarocks"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "luarocks"]
    debian: ["pkexec", "apt-get", "install", "-y", "luarocks"]
```
*(vcpkg/Conan and CocoaPods/Swift PM are deliberately left out for now — C++ and iOS toolchains are a materially different setup story that doesn't fit the "one-liner self-install" model the rest of the catalog uses. Revisit only if you actually need them.)*

**Step 4: Update `pacman` entry to mark it as driver-backed**
It already exists in the catalog from the earlier plan with `has_driver: false` — flip it to `true` once Task 2 lands, and remove its empty `self_install: {}` (a system's own native manager never needs a self-install command).

**Step 5: Tests**
Update `tests/test_catalog.py` to assert the catalog now has at least 25 entries, and that every entry's `category` is one of exactly `"System"`, `"Universal"`, or `"Language/Dev"` (catches typos early).

---

### Task 2: Implement a Full Pacman Driver

**Files:**
- Create: `app/core/drivers/pacman.py`
- Create: `tests/test_pacman_driver.py`

**Step 1: Write the driver**
```python
"""Package manager driver for Pacman (Arch Linux and derivatives like CachyOS)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class PacmanManager(PackageManager):
    """Package manager driver for Pacman."""

    name: str = "Pacman"
    category: str = "System"

    def is_available(self) -> bool:
        return shutil.which("pacman") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Qu",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            # pacman -Qu returns 1 when there are no updates, not just when there's an error —
            # only treat it as a real failure if stdout is also empty.
            if proc.returncode not in (0, 1) or not stdout:
                return []

            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                # Format: "pkgname old_version -> new_version" (optionally with "[ignored]" suffix)
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "->":
                    updates.append({"name": parts[0], "current": parts[1], "new": parts[3]})
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["pkexec", "pacman", "-S", "--noconfirm"] + packages
        return ["pkexec", "pacman", "-Syu", "--noconfirm"]

    def get_sync_command(self) -> list[str] | None:
        return ["pkexec", "pacman", "-Sy"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Qq",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return []
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["pkexec", "pacman", "-S", "--noconfirm", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pacman", "-Ss", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            results = []
            lines = stdout.decode(errors="ignore").splitlines()
            # pacman -Ss prints two lines per result: "repo/name version" then an indented description
            for i in range(0, len(lines) - 1, 2):
                header = lines[i].split()
                if len(header) >= 2:
                    repo_name = header[0]
                    name = repo_name.split("/", 1)[-1]
                    version = header[1]
                    description = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    results.append({"name": name, "id": name, "description": description, "version": version})
            return results
        except Exception:
            return []
```

**Step 2: A note on `-Qu`'s exit code**
Unlike DNF's `check-update` (0 = none, 100 = updates exist), `pacman -Qu` returns exit code `1` when there are *no* updates and `0` when there are, which is the inverse of what you'd expect coming from the DNF driver — the code above handles this explicitly rather than assuming `0` always means success, so don't "simplify" this later without re-checking pacman's actual behavior.

**Step 3: Tests**
Mock `pacman -Qu` output for: normal updates, zero updates (empty stdout, exit 1), and an `[ignored]`-suffixed line (should still parse the name/versions correctly, ignoring the trailing tag). Mock `pacman -Ss` two-line-per-result output and assert parsing.

**Step 4: Verify on your actual CachyOS machine**
This is the one driver in the whole project you can dogfood immediately, since it's your own daily-driver system's manager — run PolyGet on CachyOS after this lands and confirm the dashboard now shows System updates there for the first time.

---

### Task 3: Implement a Full RubyGems Driver

**Files:**
- Create: `app/core/drivers/gem.py`
- Create: `tests/test_gem_driver.py`

**Step 1: Write the driver**
```python
"""Package manager driver for RubyGems (globally installed Ruby gems)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class GemManager(PackageManager):
    """Package manager driver for RubyGems."""

    name: str = "RubyGems"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("gem") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "outdated",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            updates = []
            # Format: "gemname (current < available)"
            import re
            pattern = re.compile(r'^([a-zA-Z0-9_\-]+)\s+\(([^\s]+)\s*<\s*([^\s)]+)\)')
            for line in stdout.decode(errors="ignore").splitlines():
                match = pattern.match(line.strip())
                if match:
                    updates.append({"name": match.group(1), "current": match.group(2), "new": match.group(3)})
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["gem", "update"] + packages
        return ["gem", "update"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "list", "--local",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return []
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                if line.strip() and "(" in line:
                    installed.append(line.split("(")[0].strip())
            return installed
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["gem", "install", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gem", "search", "--remote", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            results = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line and "(" in line and not line.startswith("*"):
                    name = line.split("(")[0].strip()
                    version = line.split("(")[1].rstrip(")").split(",")[0].strip()
                    results.append({"name": name, "id": name, "description": "", "version": version})
            return results
        except Exception:
            return []
```
Note: unlike DNF/Pacman, `gem install`/`gem update` for user-local gems typically don't need `pkexec` (Ruby installs to `~/.gem` or a rbenv/rvm-managed path by default on most modern setups) — if your Ruby install is system-wide instead, this will need a `pkexec` prefix added, so verify which setup applies before assuming the above is correct as-is.

**Step 2: Tests**
Mock `gem outdated`, `gem list --local`, and `gem search --remote` output formats, assert parsing handles gems with pre-release version suffixes (e.g. `1.2.0.pre`) without crashing the regex.

---

### Task 4: Wrap-up — Catalog/Driver Consistency Check

**Files:**
- Modify: `tests/test_catalog.py`

**Step 1: Cross-check catalog against the registry**
Add a test asserting that every catalog entry with `has_driver: true` actually has a matching registered `PackageManager` subclass by name (catches the case where someone flips the flag in YAML but forgets to write the driver, or vice versa).

**Step 2: Manual verification**
Run PolyGet on the CachyOS desktop and confirm Pacman now appears as an active, driver-backed manager in the main dashboard (not just the catalog/store) — this is the actual proof the taxonomy expansion did something real, not just added YAML.
