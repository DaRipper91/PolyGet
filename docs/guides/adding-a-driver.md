# Guide: Adding a Package Manager Driver

This guide walks through creating and registering a new package manager driver in PolyGet.

---

## ✦ Overview

Every package manager driver in PolyGet subclasses [`PackageManager`](file:///home/daripper/Projects/PolyGet/app/core/manager.py) and is registered using the `@register_manager` decorator in [`app/core/drivers/`](file:///home/daripper/Projects/PolyGet/app/core/drivers/).

---

## ❖ Step-by-Step Implementation

### 1. Create the Driver Module
Create `app/core/drivers/my_manager.py`:

```python
from __future__ import annotations
import asyncio
from typing import Any
from app.core.manager import PackageManager, register_manager, DriverError

@register_manager
class MyManager(PackageManager):
    name = "MyManager"
    category = "Language/Dev"  # "System", "Universal", or "Language/Dev"
    supports_repos = False

    def is_available(self) -> bool:
        """Return True if the underlying CLI executable exists on PATH."""
        import shutil
        return shutil.which("mymanager") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        """Return a list of outdated packages.

        Format: [{"name": str, "current": str, "new": str}]
        Raise DriverError on real execution failures.
        """
        proc = await asyncio.create_subprocess_exec(
            "mymanager", "outdated", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise DriverError(f"mymanager check failed (exit {proc.returncode}): {stderr.decode()}")
        
        # Parse output and return standardized dicts
        return [{"name": "demo-pkg", "current": "1.0.0", "new": "1.1.0"}]

    def get_upgrade_command(self, packages: list[str]) -> list[str]:
        """Return the exact argv command list to upgrade the given packages."""
        return ["mymanager", "update", *packages]
```

### 2. Add Catalog Entry
Add the manager metadata and distro installation commands to [`app/core/data/manager_catalog.yaml`](file:///home/daripper/Projects/PolyGet/app/core/data/manager_catalog.yaml).

### 3. Write Isolated Pytest Tests
Create `tests/test_my_manager_driver.py` mocking subprocess calls:

```python
import pytest
from app.core.drivers.my_manager import MyManager

@pytest.mark.asyncio
async def test_my_manager_availability(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/mymanager" if cmd == "mymanager" else None)
    mgr = MyManager()
    assert mgr.is_available() is True
```

Run verification with offscreen Qt:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_my_manager_driver.py
```
