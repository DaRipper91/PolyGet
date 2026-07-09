# PolyGet Manager Store, Discovery Catalog, and Repos Tab Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a distro-aware package manager discovery catalog, automatic driver registration via pkgutil, self-install support for missing drivers, and a repositories/remotes management interface for DNF and Flatpak.

**Architecture:** Detect system distro family from `/etc/os-release`. Introduce a static YAML catalog of known managers. Replace hardcoded driver imports with pkgutil scanning. Extend the PackageManager base class with self-install commands and repository listing/adding/removing interfaces. Build two new tabs in the UI: "Manager Store" and "Repos".

**Tech Stack:** Python 3, PySide6, PyYAML, asyncio

---

### Task 1: Distro Family Detection

**Files:**
- Create: `app/core/distro.py`
- Create: `tests/test_distro.py`

**Step 1: Write the distro family detection utility**
Create `app/core/distro.py` with the following contents:
```python
import functools
import re

_FAMILY_MAP = {
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "arch": "arch",
    "cachyos": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "debian": "debian",
    "ubuntu": "debian",
    "suse": "suse",
    "opensuse": "suse",
    "alpine": "alpine",
    "void": "void",
    "nixos": "nix",
}

@functools.lru_cache(maxsize=1)
def get_distro_family() -> str:
    """Return a normalized distro family string by reading /etc/os-release.
    
    Checks ID first, then falls back to scanning ID_LIKE for a known family.
    Returns 'unknown' if nothing matches.
    """
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return "unknown"

    fields = dict(re.findall(r'^(\w+)=(?:"([^"]*)"|(.*))$', content, re.MULTILINE))
    
    id_val = (fields.get("ID", ("", ""))[0] or fields.get("ID", ("", ""))[1] or "").lower()
    id_like = (fields.get("ID_LIKE", ("", ""))[0] or fields.get("ID_LIKE", ("", ""))[1] or "").lower()

    if id_val in _FAMILY_MAP:
        return _FAMILY_MAP[id_val]
    
    for token in id_like.split():
        if token in _FAMILY_MAP:
            return _FAMILY_MAP[token]
            
    return "unknown"
```

**Step 2: Write tests for distro detection**
Create `tests/test_distro.py`:
```python
import pytest
from unittest.mock import mock_open, patch
from app.core.distro import get_distro_family

def test_get_distro_family_fedora():
    get_distro_family.cache_clear()
    mock_data = 'ID=fedora\nID_LIKE="rhel centos"'
    with patch("builtins.open", mock_open(read_data=mock_data)):
        assert get_distro_family() == "fedora"

def test_get_distro_family_cachyos():
    get_distro_family.cache_clear()
    mock_data = 'ID=cachyos\nID_LIKE="arch"'
    with patch("builtins.open", mock_open(read_data=mock_data)):
        assert get_distro_family() == "arch"

def test_get_distro_family_unknown():
    get_distro_family.cache_clear()
    mock_data = 'ID=gentoo\nID_LIKE="something"'
    with patch("builtins.open", mock_open(read_data=mock_data)):
        assert get_distro_family() == "unknown"
```

**Step 3: Run the test to verify it passes**
Run: `PYTHONPATH=. .venv/bin/pytest tests/test_distro.py`
Expected: PASS

**Step 4: Commit**
```bash
git add app/core/distro.py tests/test_distro.py
git commit -m "feat: implement OS/distro family detection"
```

---

### Task 2: Manager Catalog

**Files:**
- Create: `app/core/data/manager_catalog.yaml`
- Create: `app/core/data/__init__.py` (empty)
- Create: `app/core/catalog.py`
- Create: `tests/test_catalog.py`

**Step 1: Write the catalog YAML file**
Create `app/core/data/manager_catalog.yaml` with the metadata for the 14 managers (dnf, pacman, paru, flatpak, npm, pipx, cargo, apt, zypper, apk, xbps, nix, snap, distrobox) as defined in the PDF.

**Step 2: Create app/core/catalog.py loader**
Implement `CatalogEntry` dataclass and `load_catalog()` using `importlib.resources`.
```python
from dataclasses import dataclass, field
from importlib import resources
import yaml
import shutil
from app.core.manager import discover_managers
from app.core.distro import get_distro_family

@dataclass
class CatalogEntry:
    id: str
    name: str
    category: str
    description: str
    icon: str
    binary: str
    has_driver: bool
    self_install: dict[str, list[str]] = field(default_factory=dict)
    installed: bool = False

    def get_self_install_command(self) -> list[str] | None:
        """Return the install command for the current distro family, if known."""
        family = get_distro_family()
        return self.self_install.get(family)

def _binary_present(binary: str) -> bool:
    return shutil.which(binary) is not None

def load_catalog() -> list[CatalogEntry]:
    """Load the static manager catalog and annotate each entry with installed status."""
    with resources.files("app.core.data").joinpath("manager_catalog.yaml").open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    
    active_names = {mgr.name.lower() for mgr in discover_managers()}
    entries = []
    for item in raw:
        entry = CatalogEntry(**item)
        entry.installed = (entry.name.lower() in active_names or _binary_present(entry.binary))
        entries.append(entry)
    return entries
```

**Step 3: Write tests for catalog loading**
Create `tests/test_catalog.py` verifying that `load_catalog()` returns at least 14 entries and `get_self_install_command()` handles missing distros gracefully.

**Step 4: Run tests**
Run: `PYTHONPATH=. .venv/bin/pytest tests/test_catalog.py`
Expected: PASS

**Step 5: Commit**
```bash
git add app/core/data/manager_catalog.yaml app/core/catalog.py tests/test_catalog.py
git commit -m "feat: implement data-driven manager catalog loading"
```

---

### Task 3: Auto-Discovery of Driver Plugins

**Files:**
- Modify: `app/core/drivers/__init__.py`
- Modify: `tests/test_drivers_installed.py`

**Step 1: Replace hardcoded imports in app/core/drivers/__init__.py**
Use `pkgutil.iter_modules` to dynamically load driver plugins:
```python
"""Package manager driver implementations.

Importing this module auto-discovers and registers every driver module in this package,
so adding a new driver file here is sufficient - no manual import needed.
"""
import importlib
import pkgutil

for _, module_name, _ in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{module_name}")
```

**Step 2: Add test asserting registry size**
Modify `tests/test_drivers_installed.py` to assert `len(_REGISTRY) >= 5`.

**Step 3: Run the test suite**
Run: `PYTHONPATH=. .venv/bin/pytest tests/test_drivers_installed.py`
Expected: PASS

**Step 4: Commit**
```bash
git add app/core/drivers/__init__.py tests/test_drivers_installed.py
git commit -m "refactor: implement pkgutil-based auto-discovery of driver plugins"
```

---

### Task 4: Self-Install Support on the Base Class

**Files:**
- Modify: `app/core/manager.py`

**Step 1: Add get_self_install_command method**
Add to `PackageManager`:
```python
    def get_self_install_command(self) -> list[str] | None:
        """Get the command to install this manager itself on the current distro.

        Returns:
            list[str] | None: Command list, or None if unknown/unsupported.
        """
        return None
```

**Step 2: Run all tests to make sure we didn't break anything**
Run: `PYTHONPATH=. .venv/bin/pytest`
Expected: PASS

**Step 3: Commit**
```bash
git add app/core/manager.py
git commit -m "feat: add get_self_install_command interface to PackageManager"
```

---

### Task 5: Repo Support on the Base Class + First Two Implementations

**Files:**
- Modify: `app/core/manager.py`
- Modify: `app/core/drivers/dnf.py`
- Modify: `app/core/drivers/flatpak.py`
- Create: `tests/test_repos.py`

**Step 1: Extend PackageManager interface**
Add the following properties/methods to `PackageManager`:
```python
    supports_repos: bool = False

    async def list_repos(self) -> list[dict[str, Any]]:
        """List configured repositories/remotes for this manager."""
        raise NotImplementedError("This manager does not support repo listing")

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        """Get command to add repository."""
        raise NotImplementedError("This manager does not support adding repos")

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        """Get command to remove repository."""
        raise NotImplementedError("This manager does not support removing repos")
```

**Step 2: Implement for DnfManager**
Override in `DnfManager`:
- `supports_repos = True`
- `list_repos()`: executes `dnf repolist --all --quiet` and parses output.
- `get_add_repo_command()`: checks if it contains `/` (COPR shorthand) and generates `dnf copr enable` or `dnf config-manager --add-repo`.
- `get_remove_repo_command()`: runs `dnf config-manager --set-disabled`.

**Step 3: Implement for FlatpakManager**
Override in `FlatpakManager`:
- `supports_repos = True`
- `list_repos()`: executes `flatpak remotes --columns=name,url,disabled` and parses output.
- `get_add_repo_command()`: adds custom flatpak remote.
- `get_remove_repo_command()`: runs `flatpak remote-delete`.

**Step 4: Write tests for repo management**
Create `tests/test_repos.py` verifying correct parsing and command generation.

**Step 5: Run tests**
Run: `PYTHONPATH=. .venv/bin/pytest tests/test_repos.py`
Expected: PASS

**Step 6: Commit**
```bash
git add app/core/manager.py app/core/drivers/dnf.py app/core/drivers/flatpak.py tests/test_repos.py
git commit -m "feat: implement repo/remote management support for DNF and Flatpak"
```

---

### Task 6: UI — Manager Store Section

**Files:**
- Modify: `app/ui/main_window.py`

**Step 1: Refactor navigation sidebar**
Change sidebar lists to include the new "Manager Store" navigation item.

**Step 2: Build the Manager Store page**
Build a grid/list utilizing `load_catalog()` to display all registered managers, active/inactive badges, descriptions, and a styled "Install" button.

**Step 3: Wire self-install action**
Trigger installation of the driver backend through `ExecutionWorker` when clicking "Install". Trigger UI catalog refresh upon successful installation.

**Step 4: Commit**
```bash
git add app/ui/main_window.py
git commit -m "feat: build Manager Store view inside GUI navigation"
```

---

### Task 7: UI — Repos Tab

**Files:**
- Modify: `app/ui/main_window.py`

**Step 1: Add Repos navigation item**
Add "Repository Sources" to nav sidebar. Only show/enable if any active manager supports repositories.

**Step 2: Build the Repos page**
Display a sidebar listing managers where `mgr.supports_repos` is True, and a main details panel listing active repos, checkboxes to enable/disable, and a remove button. Add an "Add Repository" input box calling `get_add_repo_command()`.

**Step 3: Commit**
```bash
git add app/ui/main_window.py
git commit -m "feat: implement Repository Sources tab in GUI"
```

---

### Task 8: Wrap-up Tests

**Files:**
- Modify: `tests/test_blueprint_gui.py`

**Step 1: Write integration tests**
Verify the end-to-end functionality of the Manager Store list, Repos list, and their worker slots under offscreen testing.

**Step 2: Run all tests**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: PASS

**Step 3: Commit**
```bash
git add tests/test_blueprint_gui.py
git commit -m "test: add integration tests for repository and manager store UI controllers"
```
