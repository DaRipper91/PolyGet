# PolyGet: Expand Language/Dev Coverage — Yarn, pnpm, Poetry, Dart, Hex, Perl, Julia

> **For Antigravity:** This plan assumes the catalog/discovery plan and the taxonomy-expansion plan (Pacman, RubyGems) have already landed. Read Section 0 before writing any code — two of the originally-requested managers (Bundler, Gradle) are deliberately **not** getting full drivers, and the reasoning matters for future additions too.

**Goal:** Add full working drivers for the highest-value remaining Language/Dev package managers, completing coverage of the ecosystems actually in daily use (Node, Python, Ruby-adjacent, Dart/Flutter, Elixir, Perl, Julia).

---

## 0. Why Bundler and Gradle Are Catalog-Only, Not Full Drivers

PolyGet's `PackageManager` interface (`check_updates`, `list_installed`, `get_upgrade_command`) assumes a manager tracks a **global, system-wide list of installed packages** — that's true for every existing driver (DNF, Pacman, npm, Cargo, Pipx, RubyGems). Bundler and Gradle don't have that concept: a `Gemfile.lock` or `build.gradle` is scoped to one project directory, not the whole system. There is no "list every Bundler-managed gem on this machine" the way there's "list every RubyGems gem" — that question doesn't have a coherent answer, since it depends entirely on *which project* you mean.

A driver that pretends otherwise would either always report zero results, or require the UI to ask "which project directory?" before doing anything — a fundamentally different interaction than the rest of the dashboard. Rather than build something that quietly misleads, both stay **catalog-only** (metadata + self-install command, so they're still visible and installable from the Manager Store), with a comment in the catalog YAML explaining why no driver exists. If PolyGet ever grows a per-project view (a genuinely different feature), revisit this — don't force it into the current global-list model.

**Files:**
- Modify: `app/core/data/manager_catalog.yaml`

```yaml
- id: bundler
  name: Bundler
  category: Language/Dev
  # No full driver: Bundler is inherently per-project (Gemfile.lock), not a
  # global installed-package list like RubyGems. See taxonomy-expansion plan
  # Section 0 for the reasoning — don't add a driver that fakes global scope.
  description: Ruby's per-project dependency manager (Gemfile.lock).
  icon: text-x-generic
  binary: bundle
  has_driver: false
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "rubygem-bundler"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "ruby-bundler"]
    debian: ["pkexec", "apt-get", "install", "-y", "ruby-bundler"]

- id: gradle
  name: Gradle
  category: Language/Dev
  # No full driver: same reasoning as Bundler above — Gradle's dependency
  # scope is per-project (build.gradle), not a global package list.
  description: Java/Kotlin per-project build and dependency tool.
  icon: text-x-generic
  binary: gradle
  has_driver: false
  self_install:
    fedora: ["pkexec", "dnf", "install", "-y", "gradle"]
    arch: ["sudo", "pacman", "-S", "--noconfirm", "gradle"]
    debian: ["pkexec", "apt-get", "install", "-y", "gradle"]
```

---

## 1. Yarn Driver

**Files:** Create `app/core/drivers/yarn.py`, `tests/test_yarn_driver.py`

```python
"""Package manager driver for Yarn (Node.js, global installs)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class YarnManager(PackageManager):
    name: str = "Yarn"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("yarn") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "yarn", "global", "outdated", "--json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            import json
            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "table":
                    for row in obj.get("data", {}).get("body", []):
                        if len(row) >= 4:
                            updates.append({"name": row[0], "current": row[1], "new": row[3]})
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["yarn", "global", "add"] + packages
        return ["yarn", "global", "upgrade"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "yarn", "global", "list", "--depth=0",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("info") or "@" not in line:
                    continue
                # Format: '- packagename@version'
                name = line.lstrip("- ").rsplit("@", 1)[0]
                if name:
                    installed.append(name)
            return installed
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["yarn", "global", "add", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Yarn Classic has no built-in search command; it shares npm's registry,
        # so delegate to the npm registry search API directly rather than
        # reinventing it — same registry, same package names.
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "search", "--json", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": i.get("name", ""), "id": i.get("name", ""),
                     "description": i.get("description", ""), "version": i.get("version", "")}
                    for i in data[:20]] if isinstance(data, list) else []
        except Exception:
            return []
```
Note the deliberate dependency on `npm` for search — Yarn Classic never shipped its own registry search command, and Yarn Berry deprecated `yarn search` entirely. If `npm` isn't installed, this returns `[]` silently, which is acceptable (Yarn without npm present at all is a rare setup).

---

## 2. pnpm Driver

**Files:** Create `app/core/drivers/pnpm.py`, `tests/test_pnpm_driver.py`

```python
"""Package manager driver for pnpm (Node.js, global installs)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class PnpmManager(PackageManager):
    name: str = "pnpm"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("pnpm") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pnpm", "outdated", "--global", "--format", "json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            import json
            data = json.loads(stdout.decode(errors="ignore") or "{}")
            return [{"name": name, "current": info.get("current", ""), "new": info.get("latest", "")}
                    for name, info in data.items()]
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["pnpm", "add", "--global"] + packages
        return ["pnpm", "update", "--global"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pnpm", "list", "--global", "--depth=0", "--json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            import json
            data = json.loads(stdout.decode(errors="ignore") or "[]")
            deps = data[0].get("dependencies", {}) if data else {}
            return list(deps.keys())
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["pnpm", "add", "--global", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Same reasoning as Yarn — pnpm has no native search, shares npm's registry.
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "search", "--json", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": i.get("name", ""), "id": i.get("name", ""),
                     "description": i.get("description", ""), "version": i.get("version", "")}
                    for i in data[:20]] if isinstance(data, list) else []
        except Exception:
            return []
```

---

## 3. Dart/Flutter pub Driver

**Files:** Create `app/core/drivers/dart_pub.py`, `tests/test_dart_pub_driver.py`

```python
"""Package manager driver for Dart's pub (global-activated CLI packages)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class DartPubManager(PackageManager):
    name: str = "Dart Pub"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("dart") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "dart", "pub", "global", "list",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                if line.strip():
                    installed.append(line.split()[0])
            return installed
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # `dart pub global` has no built-in outdated-check across all globally
        # activated packages — only per-package via reactivation. Re-activating
        # every installed package just to detect drift is expensive and noisy,
        # so this intentionally returns [] rather than faking a check.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["dart", "pub", "global", "activate"] + packages
        return ["dart", "pub", "global", "activate"]  # no bulk-upgrade-all equivalent exists

    def get_install_command(self, package: str) -> list[str]:
        return ["dart", "pub", "global", "activate", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # pub.dev has a documented search API (unlike PyPI) — use it directly.
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", f"https://pub.dev/api/search?q={query}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": p.get("package", ""), "id": p.get("package", ""),
                     "description": "", "version": ""} for p in data.get("packages", [])[:20]]
        except Exception:
            return []
```
Flag this one explicitly: `check_updates()` returns an empty list always, by design, not by bug — don't "fix" it into a fake implementation later without solving the actual reactivation-cost problem described in the comment.

---

## 4. Elixir Hex Driver

**Files:** Create `app/core/drivers/hex.py`, `tests/test_hex_driver.py`

```python
"""Package manager driver for Elixir's Hex (globally installed Mix archives/escripts)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class HexManager(PackageManager):
    name: str = "Hex"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("mix") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "mix", "archive",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip().rstrip("*").strip()
                if line and line.endswith(".ez"):
                    installed.append(line.rsplit("-", 1)[0].replace(".ez", ""))
            return installed
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # Mix archives don't have a bulk "list what's outdated" command —
        # each would need an individual hex.pm version lookup. Left empty
        # rather than faking it; revisit if per-archive lookups prove cheap enough.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["mix", "archive.install", "hex"] + packages + ["--force"]
        return ["mix", "local.hex", "--force"]

    def get_install_command(self, package: str) -> list[str]:
        return ["mix", "archive.install", "hex", package, "--force"]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", f"https://hex.pm/api/packages?search={query}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            return [{"name": p.get("name", ""), "id": p.get("name", ""),
                     "description": (p.get("meta") or {}).get("description", ""),
                     "version": ((p.get("releases") or [{}])[0]).get("version", "")}
                    for p in data[:20]]
        except Exception:
            return []
```

---

## 5. Perl (cpanm) Driver

**Files:** Create `app/core/drivers/cpanm.py`, `tests/test_cpanm_driver.py`

```python
"""Package manager driver for Perl's cpanminus (globally installed CPAN modules)."""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class CpanmManager(PackageManager):
    name: str = "cpanm"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("cpanm") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "perl", "-MExtUtils::Installed", "-e",
                "print join(qq(\\n), ExtUtils::Installed->new->modules)",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # No built-in bulk outdated-check without the separate `cpan-outdated`
        # tool, which isn't a safe assumption to have installed — return []
        # rather than silently depending on an optional third tool.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["cpanm"] + packages
        return ["cpanm", "--self-upgrade"]

    def get_install_command(self, package: str) -> list[str]:
        return ["cpanm", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # MetaCPAN has a real, documented public search API — use it directly.
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", f"https://fastapi.metacpan.org/v1/module/_search?q={query}&size=20",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            import json
            data = json.loads(stdout.decode(errors="ignore"))
            hits = data.get("hits", {}).get("hits", [])
            return [{"name": h["_source"].get("name", ""), "id": h["_source"].get("name", ""),
                     "description": "", "version": h["_source"].get("version", "")} for h in hits]
        except Exception:
            return []
```

---

## 6. Poetry Driver (scoped to `poetry self` plugins)

**Files:** Create `app/core/drivers/poetry.py`, `tests/test_poetry_driver.py`

```python
"""Package manager driver for Poetry — tracks Poetry's own global plugins only.

Poetry's actual dependency management (pyproject.toml/poetry.lock) is inherently
per-project, same reasoning as Bundler (see taxonomy plan Section 0). What IS
global and trackable is `poetry self` — the plugins installed into Poetry's own
environment. That's the scope of this driver; it deliberately does not attempt
to surface arbitrary project dependencies.
"""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class PoetryManager(PackageManager):
    name: str = "Poetry"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("poetry") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "poetry", "self", "show",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            installed = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.split()
                if parts and parts[0] and not line.startswith(" "):
                    installed.append(parts[0])
            return installed
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        return []  # no bulk outdated-check for self plugins; low churn, low value to fake

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["poetry", "self", "update"] + packages
        return ["poetry", "self", "update"]

    def get_install_command(self, package: str) -> list[str]:
        return ["poetry", "self", "add", package]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # Poetry plugins are just PyPI packages tagged appropriately — reuse
        # the same local-index approach as pipx.py rather than duplicating it.
        from app.core.drivers.pipx import PipxManager
        return await PipxManager().search_packages(query)
```

---

## 7. Julia Driver (scoped to the default global environment)

**Files:** Create `app/core/drivers/julia.py`, `tests/test_julia_driver.py`

```python
"""Package manager driver for Julia's Pkg — tracks the default global environment only.

Julia's per-project environments (Project.toml) are out of scope for the same
reason as Bundler/Poetry-project-deps. The default global environment (`@v1.x`)
IS a real, single, trackable package list, so that's what this driver covers.
"""

import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class JuliaManager(PackageManager):
    name: str = "Julia"
    category: str = "Language/Dev"

    def is_available(self) -> bool:
        return shutil.which("julia") is not None

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "julia", "-e", "using Pkg; for (k,v) in Pkg.dependencies(); println(v.name); end",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            return sorted(set(line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()))
        except Exception:
            return []

    async def check_updates(self) -> list[dict[str, Any]]:
        # Pkg.outdated() output isn't line-parseable in a stable way across
        # Julia versions without significant extra scripting — left empty
        # rather than a brittle parse that breaks on the next Julia release.
        return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            pkg_list = ", ".join(f'"{p}"' for p in packages)
            return ["julia", "-e", f"using Pkg; Pkg.update([{pkg_list}])"]
        return ["julia", "-e", "using Pkg; Pkg.update()"]

    def get_install_command(self, package: str) -> list[str]:
        return ["julia", "-e", f'using Pkg; Pkg.add("{package}")']

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        # No official Julia registry search HTTP API — General registry search
        # tools exist as third-party sites only, not a stable programmatic
        # endpoint. Returning [] honestly rather than scraping a webpage.
        return []
```
This one's the most limited of the batch — flag it clearly in the Manager Store UI (via the catalog's `has_driver: true` but effectively reduced capability) so it doesn't look broken when search comes back empty; that's expected, not a bug.

---

## 8. Catalog Updates

**Files:** Modify `app/core/data/manager_catalog.yaml`

Flip `has_driver: true` for: `yarn`, `pnpm`, `dart-pub`, `hex`, `cpanm`, `poetry`, `julia` (add entries for any not already present, following the existing schema pattern with `self_install` per distro family).

---

## 9. Wrap-up

**Files:** Modify `tests/test_catalog.py`

- Assert catalog entry count reflects all new additions.
- Assert every `has_driver: true` entry has a matching registered class (existing consistency check from the taxonomy plan — just needs to now cover 7 more).
- For Dart Pub, Hex, cpanm, Poetry, and Julia specifically: add a test asserting `check_updates()` returns `[]` without raising, so a future refactor doesn't accidentally introduce a crash where "not implemented yet" was the intentional, documented behavior.
