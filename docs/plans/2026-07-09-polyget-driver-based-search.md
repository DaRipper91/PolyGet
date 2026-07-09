# PolyGet Driver-Based Package Search Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move package search logic from the UI thread/SearchWorker into the respective package manager driver classes. Fix the Flatpak search JSON bug, and implement a local-cache search for Pipx using the PyPI Simple Index.

**Architecture:** Add `search_packages(query)` to the base `PackageManager` class. Migrate DNF, Cargo, and NPM search logic to their driver classes. Implement tab-separated Flatpak search parsing. Add local PyPI simple index cache for Pipx case-insensitive substring searching. Refactor `SearchWorker` to generically loop over all active managers.

**Tech Stack:** Python 3, PySide6, asyncio

---

### Task 1: Add search_packages() to the Base Class

**Files:**
- Modify: `app/core/manager.py`
- Modify: `tests/test_drivers_installed.py`

**Step 1: Add search_packages method**
Add to `PackageManager`:
```python
    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        """Search this manager's package source for a query string.

        Args:
            query (str): The search query.

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing matching packages.
                Each dict must contain: 'name', 'id', 'description', 'version'.
                Callers will add the 'source' key themselves.
        """
        raise NotImplementedError(f"{self.name} does not support package search")
```

**Step 2: Run all tests to verify it works**
Run: `PYTHONPATH=. .venv/bin/pytest`
Expected: PASS

**Step 3: Commit**
```bash
git add app/core/manager.py
git commit -m "feat: add search_packages interface to PackageManager"
```

---

### Task 2: Migrate DNF, Cargo, NPM Search Logic Into Their Drivers

**Files:**
- Modify: `app/core/drivers/dnf.py`
- Modify: `app/core/drivers/cargo.py`
- Modify: `app/core/drivers/npm.py`
- Modify: `tests/test_dnf_driver.py`
- Create: `tests/test_cargo_driver.py`
- Create: `tests/test_npm_driver_search.py`

**Step 1: DNF search implementation**
Implement `search_packages` in `DnfManager` executing `dnf search` with a `12.0`s timeout.

**Step 2: Cargo search implementation**
Implement `search_packages` in `CargoManager` executing `cargo search --limit 20` with a `15.0`s timeout.

**Step 3: NPM search implementation**
Implement `search_packages` in `NpmManager` executing `npm search --json` with a `15.0`s timeout.

**Step 4: Create driver tests**
Create unit tests verifying correct parser outputs for DNF, Cargo, and NPM search methods.

**Step 5: Run tests**
Run: `PYTHONPATH=. .venv/bin/pytest tests/test_dnf_driver.py tests/test_cargo_driver.py tests/test_npm_driver_search.py`
Expected: PASS

**Step 6: Commit**
```bash
git add app/core/drivers/dnf.py app/core/drivers/cargo.py app/core/drivers/npm.py tests/
git commit -m "feat: migrate DNF, Cargo, NPM search logic into driver classes"
```

---

### Task 3: Fix and Migrate Flatpak Search

**Files:**
- Modify: `app/core/drivers/flatpak.py`
- Create: `tests/test_flatpak_search.py`

**Step 1: Flatpak search implementation**
Implement `search_packages` in `FlatpakManager` executing `flatpak search --columns=name,description,application,version,remotes` with a `10.0`s timeout. Parse tab-separated output.

**Step 2: Create tests for Flatpak search**
Create unit tests verifying correct parsing of tab-separated columns, including cases with empty remotes.

**Step 3: Run tests**
Run: `PYTHONPATH=. .venv/bin/pytest tests/test_flatpak_search.py`
Expected: PASS

**Step 4: Commit**
```bash
git add app/core/drivers/flatpak.py tests/test_flatpak_search.py
git commit -m "fix: implement correct tab-separated Flatpak search parsing"
```

---

### Task 4: Give Pipx a Real Search (Local Index Cache)

**Files:**
- Modify: `app/core/drivers/pipx.py`
- Create: `tests/test_pipx_search.py`

**Step 1: PyPI Simple Index cache loader**
Implement `_ensure_index_cached()` in `PipxManager` downloading `https://pypi.org/simple/` with `Accept: application/vnd.pypi.simple.v1+json` and saving to `~/.cache/polyget/pypi_simple_index.json` (max age 1 week).

**Step 2: Substring matching and details query**
Implement `search_packages` doing case-insensitive substring matching on the cached index. Fetch top 20 matches descriptions on PyPI JSON API: `https://pypi.org/pypi/{name}/json`.

**Step 3: Create tests for Pipx search**
Create tests mocking the cached simple index file, verifying case-insensitive substring matching, and details JSON fetching.

**Step 4: Run tests**
Run: `PYTHONPATH=. .venv/bin/pytest tests/test_pipx_search.py`
Expected: PASS

**Step 5: Commit**
```bash
git add app/core/drivers/pipx.py tests/test_pipx_search.py
git commit -m "feat: implement local index cached PyPI search for Pipx driver"
```

---

### Task 5: Refactor SearchWorker to Loop Over discover_managers()

**Files:**
- Modify: `app/ui/main_window.py`

**Step 1: Refactor SearchWorker.run()**
Replace the five hardcoded functions with a loop over `discover_managers()` calling `mgr.search_packages()`.

**Step 2: Refactor combo_source population**
Check where `combo_source` items are populated and switch to using dynamic `[m.name for m in discover_managers()]`.

**Step 3: Run the app and run the test suite**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: PASS

**Step 4: Commit**
```bash
git add app/ui/main_window.py
git commit -m "refactor: simplify SearchWorker to use generic driver-based search loops"
```

---

### Task 6: Wrap-up

**Files:**
- Modify: `tests/test_drivers_installed.py`

**Step 1: Add wrap-up assertions**
Add a test asserting that all 5 active drivers correctly respond to `search_packages()` or raise `NotImplementedError`.

**Step 2: Final tests run**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: PASS

**Step 3: Commit**
```bash
git add tests/test_drivers_installed.py
git commit -m "test: add final package search capabilities assertions"
```
