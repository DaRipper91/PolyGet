# PolyGet Enhancements and Features Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement memory leak fixes, parallelize update checks, secure privilege elevation, prevent zombie processes, and build two major new features (PolySync declarative blueprinting and PolyGuard native Polkit/lifecycle coordination).

**Architecture:** 
1. Core upgrades include parallelizing the Pipx subprocess calls with `asyncio.gather` and connecting `finished` signals of QThreads to cleanup slots.
2. PolyGuard implements a singleton subprocess coordinator using OS process groups to track and kill processes, and delegates privilege elevation to PolicyKit (`pkexec`).
3. PolySync defines new abstract methods on the driver interfaces to query list of installed packages and compose installation commands, then serializes the multi-backend state to YAML blueprints.

**Tech Stack:** Python 3, PySide6, PyYAML, asyncio

---

### Task 1: UI QThread Memory Leak Cleanup

**Files:**
- Modify: `app/ui/main_window.py`

**Step 1: Write a verification script for QThread lifetime**
Verify that workers are appended to `self.active_workers` but never removed.

**Step 2: Implement cleanup connection logic**
Modify `app/ui/main_window.py` to auto-cleanup finished workers.
Connect the worker's `finished` signal to a lambda/method that removes the worker from `self.active_workers` and calls `worker.deleteLater()`.

Find all occurrences of `self.active_workers.append(worker)` and ensure they connect:
```python
worker.finished.connect(lambda w=worker: self.active_workers.remove(w) if w in self.active_workers else None)
worker.finished.connect(worker.deleteLater)
```

**Step 3: Run verification test**
Ensure that `len(self.active_workers)` decreases when scan or update threads complete.

---

### Task 2: Parallelize Pipx Package Audits

**Files:**
- Modify: `app/core/drivers/pipx.py`

**Step 1: Write a unit test representing parallel Pipx package check**
Create `tests/test_pipx_driver.py` using `pytest`:
```python
import pytest
import asyncio
from app.core.drivers.pipx import PipxManager

@pytest.mark.asyncio
async def test_pipx_is_available():
    manager = PipxManager()
    assert isinstance(manager.is_available(), bool)
```

**Step 2: Implement parallel processing using asyncio.gather**
Modify `app/core/drivers/pipx.py` line 22:
```python
    async def check_updates(self) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pipx", "list", "--short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            
            import os
            pipx_home = os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/share/pipx"))
            
            async def check_single(name: str) -> dict[str, Any] | None:
                try:
                    pip_path = os.path.join(pipx_home, "venvs", name, "bin", "pip")
                    if os.path.exists(pip_path):
                        pip_proc = await asyncio.create_subprocess_exec(
                            pip_path, "list", "--outdated", "--json",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        pip_stdout, _ = await pip_proc.communicate()
                        if pip_stdout:
                            import json
                            pip_data = json.loads(pip_stdout.decode(errors="ignore"))
                            for item in pip_data:
                                if item.get("name") == name:
                                    return {
                                        "name": name,
                                        "current": item.get("version", "Unknown"),
                                        "new": item.get("latest_version", "Latest")
                                    }
                except Exception:
                    pass
                return None

            tasks = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    tasks.append(check_single(parts[0]))
            
            results = await asyncio.gather(*tasks)
            return [r for r in results if r is not None]
        except Exception:
            return []
```

**Step 3: Run the test**
Run: `.venv/bin/pytest tests/test_pipx_driver.py -v`
Expected: PASS

---

### Task 3: Eliminate Synchronous Blocking in NPM Driver

**Files:**
- Modify: `app/core/drivers/npm.py`

**Step 1: Identify blocking call**
Identify the synchronous `subprocess.run` inside `get_upgrade_command()` in `app/core/drivers/npm.py`.

**Step 2: Refactor to cached asynchronous property or safe async discovery**
Modify `app/core/drivers/npm.py`:
Add a cached `_prefix` field or run standard `npm config get prefix` asynchronously inside `is_available()` or dynamic check. Alternatively, since it is a fallback wrapper for `sudo`, we can run it asynchronously or read it during discovery:
```python
    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        # Perform check via local environment or async task
        # Fallback to standard command - prefix is typically /usr or ~/.npm-global
        base_cmd = ["npm", "update", "-g"]
        if packages:
            base_cmd = base_cmd + packages
        
        # We can look up the prefix using environment variable prefix or write permission checks directly on known folders, avoiding blocking subprocess calls in this method.
        # Fallback to standard check or standard environment path check:
        import os
        prefix = os.environ.get("NPM_CONFIG_PREFIX")
        if not prefix:
            # Check standard path
            prefix = "/usr"
        if not os.access(prefix, os.W_OK):
            return ["sudo"] + base_cmd
        return base_cmd
```

**Step 3: Verify no UI lag occurs when NPM packages are loaded**

---

### Task 4: Subprocess Lifecycle Coordinator (PolyGuard)

**Files:**
- Create: `app/core/coordinator.py`
- Modify: `app/ui/main_window.py`

**Step 1: Implement Coordinator**
Create `app/core/coordinator.py`:
```python
import os
import signal
import subprocess
from typing import Set

class SubprocessCoordinator:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.active_pids: Set[int] = set()

    def register_pid(self, pid: int):
        self.active_pids.add(pid)

    def unregister_pid(self, pid: int):
        self.active_pids.discard(pid)

    def terminate_all(self):
        for pid in list(self.active_pids):
            try:
                # Send SIGTERM to the process group
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
        self.active_pids.clear()
```

**Step 2: Integrate Process Groups in Subprocesses**
Update [ExecutionWorker.run](file:///home/daripper/Projects/PolyGet/app/ui/main_window.py#L92-L138) to use process groups and register with coordinator:
```python
                proc = await asyncio.create_subprocess_exec(
                    *run_cmd_list,
                    stdin=asyncio.subprocess.PIPE if use_sudo else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    preexec_fn=os.setsid
                )
                SubprocessCoordinator.instance().register_pid(proc.pid)
                # ... when finished:
                SubprocessCoordinator.instance().unregister_pid(proc.pid)
```

**Step 3: Modify Close Event in UI**
Modify `app/ui/main_window.py` to prompt user and call `terminate_all()` on close:
```python
    def closeEvent(self, event):
        from app.core.coordinator import SubprocessCoordinator
        if SubprocessCoordinator.instance().active_pids:
            reply = QMessageBox.question(
                self, "Active Processes Running",
                "Package operations are currently running in the background. Are you sure you want to force exit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                SubprocessCoordinator.instance().terminate_all()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
```

---

### Task 5: Secure PolicyKit Privilege Elevation (PolyGuard)

**Files:**
- Modify: `app/ui/main_window.py`, `app/core/drivers/dnf.py`

**Step 1: Check availability of pkexec**
In drivers that require root privileges (like `DnfManager`), run command with `pkexec` prefix.

**Step 2: Modify command construction**
Change `get_upgrade_command()` and `get_sync_command()` in `app/core/drivers/dnf.py` to use `pkexec` instead of `sudo`:
```python
    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["pkexec", "dnf", "upgrade", "-y"] + packages
        return ["pkexec", "dnf", "upgrade", "-y"]

    def get_sync_command(self) -> list[str] | None:
        return ["pkexec", "dnf", "makecache"]
```
Also modify `DnfManager.check_updates()` to NOT require root privileges (remove `sudo -S` and just run `dnf check-update --json` or standard check):
```python
            proc = await asyncio.create_subprocess_exec(
                "dnf", "check-update", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
```

**Step 3: Refactor ExecutionWorker to support pkexec**
Modify `ExecutionWorker.run` in `app/ui/main_window.py` to handle `pkexec` (remove `sudo` stdin writes of hardcoded `"0"` password).

---

### Task 6: Declarative Blueprint Module (PolySync)

**Files:**
- Create: `app/core/blueprint.py`

**Step 1: Define core blueprint structure**
Create `app/core/blueprint.py`:
```python
import yaml
from typing import Any, Dict

class BlueprintManager:
    @staticmethod
    def generate_blueprint(installed_packages: Dict[str, list]) -> str:
        """Serialize package lists across backends to a YAML string."""
        data = {
            "version": "1.0.0",
            "backends": installed_packages
        }
        return yaml.safe_dump(data, default_flow_style=False)

    @staticmethod
    def parse_blueprint(content: str) -> Dict[str, list]:
        """Deserialize a YAML string to a dictionary of backend package lists."""
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict) and "backends" in data:
                return data["backends"]
        except Exception:
            pass
        return {}
```

**Step 2: Write tests for blueprint serialization**
Create `tests/test_blueprint.py`:
```python
from app.core.blueprint import BlueprintManager

def test_serialization():
    data = {
        "dnf": ["git", "neovim"],
        "flatpak": ["org.kde.kate"]
    }
    yaml_str = BlueprintManager.generate_blueprint(data)
    parsed = BlueprintManager.parse_blueprint(yaml_str)
    assert parsed["dnf"] == ["git", "neovim"]
    assert parsed["flatpak"] == ["org.kde.kate"]
```

**Step 3: Run test**
Run: `.venv/bin/pytest tests/test_blueprint.py -v`
Expected: PASS

---

### Task 7: Implement installed package lists on drivers (PolySync)

**Files:**
- Modify: `app/core/manager.py`
- Modify: `app/core/drivers/dnf.py`, `app/core/drivers/flatpak.py`, `app/core/drivers/pipx.py`, `app/core/drivers/npm.py`, `app/core/drivers/cargo.py`

**Step 1: Add abstract methods to PackageManager**
Update `app/core/manager.py`:
```python
    async def list_installed(self) -> list[str]:
        """Asynchronously return a list of installed package names."""
        raise NotImplementedError("Subclasses must implement list_installed()")

    def get_install_command(self, package: str) -> list[str]:
        """Get the command to install a specific package."""
        raise NotImplementedError("Subclasses must implement get_install_command()")
```

**Step 2: Implement list_installed and get_install_command in all drivers**
Modify each driver to implement these methods.

Example for `PipxManager`:
```python
    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pipx", "list", "--short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            packages = []
            for line in stdout.decode(errors="ignore").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    packages.append(parts[0])
            return packages
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["pipx", "install", package]
```

Repeat for all other drivers (DNF, Flatpak, NPM, Cargo).

---

### Task 8: PolySync GUI Tab Integration

**Files:**
- Modify: `app/ui/main_window.py`

**Step 1: Design and setup layout for PolySync Tab**
Modify `setup_ui()` in `app/ui/main_window.py` to add a new sidebar navigation option ("Blueprints") and a corresponding page in `self.stacked_widget`.
The page contains:
- Text editor displaying/editing YAML configuration.
- Buttons: "Export Current Setup", "Import Blueprint", "Apply Sync".

**Step 2: Wire up Export, Import, and Apply Actions**
- **Export**: Queries `list_installed()` on all active managers, calls `BlueprintManager.generate_blueprint()`, and loads it into the editor.
- **Import**: Opens a file dialog to load YAML and displays it in the editor.
- **Apply Sync**: Compares the loaded YAML with the currently installed packages on the system. Any package missing in `list_installed()` will be appended to an installation queue and installed using `get_install_command()`.

**Step 3: Run the app and verify PolySync and PolyGuard are functioning correctly**
Launch the GUI: `python run.py`
Verify all screens display correctly, the thread count stays low, and close prompts trigger appropriately.
