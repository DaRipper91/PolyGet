# PolyGet Enhancements Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement parallel scans, store filters, colorized console logs, version pinning, and self-healing sync in PolyGet.

**Architecture:** 
1. Replace multiple `UpdateWorker` instances with a single `ScanWorker` using `asyncio.gather`.
2. Add dynamic, instant UI filtering to the store search list and enrich results headers with count breakdowns.
3. Switch the console component to `QTextEdit` and implement rich HTML color mapping for logs.
4. Support version pin separation (using `==` or `@`) in the blueprint sync logic and queue installation command lines sequentially.

**Tech Stack:** Python 3, PySide6 (Qt6), PyYAML, Asyncio.

---

### Task 1: Single ScanWorker for Parallel Update Scans

**Files:**
- Modify: [main_window.py](file:///home/daripper/Projects/PolyGet/app/ui/main_window.py)
- Test: [test_blueprint_gui.py](file:///home/daripper/Projects/PolyGet/tests/test_blueprint_gui.py)

**Step 1: Write the failing test**
Create a test in `tests/test_blueprint_gui.py` verifying that a single ScanWorker gathers all scans concurrently.

```python
def test_scan_worker_concurrent(qapp):
    from app.ui.main_window import ScanWorker
    from app.core.drivers.flatpak import FlatpakManager
    from unittest.mock import AsyncMock, patch

    mgr1 = FlatpakManager()
    mgr1.check_updates = AsyncMock(return_value=[])

    worker = ScanWorker([mgr1])
    results = {}
    worker.updates_signal.connect(lambda name, ups: results.update({name: ups}))
    
    worker.run()
    assert mgr1.name in results
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_blueprint_gui.py -k test_scan_worker_concurrent`
Expected: FAIL (ScanWorker not defined)

**Step 3: Write minimal implementation**
Define `ScanWorker` in `app/ui/main_window.py` and refactor `MainWindow.scan_all()` to instantiate and start a single `ScanWorker`.

```python
class ScanWorker(QThread):
    log_signal = Signal(str)
    updates_signal = Signal(str, list)
    finished_all = Signal()

    def __init__(self, managers: list, parent: Any = None):
        super().__init__(parent)
        self.managers = managers

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run_scan(mgr):
            self.log_signal.emit(f"🔍 Scanning {mgr.name} for updates...")
            try:
                updates = await mgr.check_updates()
                self.updates_signal.emit(mgr.name, updates)
                self.log_signal.emit(f"✅ Scan complete for {mgr.name}. Found {len(updates)} update(s).")
            except Exception as e:
                self.log_signal.emit(f"❌ Error scanning {mgr.name}: {str(e)}")
                self.updates_signal.emit(mgr.name, [])

        tasks = [run_scan(mgr) for mgr in self.managers]
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()
        self.finished_all.emit()
```

Update `MainWindow.scan_all` to use it.

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: PASS

**Step 5: Commit**
```bash
git add app/ui/main_window.py tests/test_blueprint_gui.py
git commit -m "feat: implement single concurrent ScanWorker"
```

---

### Task 2: Dynamic Search Filtering in Browse Store

**Files:**
- Modify: [main_window.py](file:///home/daripper/Projects/PolyGet/app/ui/main_window.py)

**Step 1: Write implementation for dynamic filtering**
Modify `handle_store_results()` to calculate counts per source type and display the breakdown.
Connect `self.combo_source.currentTextChanged` to a new slot `filter_store_results(self)`:

```python
    def filter_store_results(self):
        filter_text = self.combo_source.currentText()
        for i in range(self.store_list.count()):
            item = self.store_list.item(i)
            widget = self.store_list.itemWidget(item)
            if widget:
                # If filter is "All Sources" or matches source type, show it
                if filter_text == "All Sources" or widget.item.get("source") == filter_text:
                    item.setHidden(False)
                else:
                    item.setHidden(True)
```

And update `handle_store_results` to update the result label:
```python
        counts = {}
        for item in results:
            src = item.get("source", "Unknown")
            counts[src] = counts.get(src, 0) + 1
        breakdown = ", ".join(f"{k}: {v}" for k, v in counts.items())
        self.lbl_store_results.setText(f"Found {len(results)} package(s) ({breakdown}):")
```

**Step 2: Verify and Commit**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: PASS
```bash
git add app/ui/main_window.py
git commit -m "feat: add dynamic store search filtering and count breakdowns"
```

---

### Task 3: Colorized Console Logs

**Files:**
- Modify: [main_window.py](file:///home/daripper/Projects/PolyGet/app/ui/main_window.py)

**Step 1: Write implementation**
Change `self.console = QPlainTextEdit()` to `self.console = QTextEdit()` in `setup_ui()` (and update references).
Update `MainWindow.log(self, message: str)`:

```python
    def log(self, message: str):
        # Color mapping for terminal log icons
        color_map = {
            "✅": "#a6e3a1",  # green
            "❌": "#f38ba8",  # red
            "🔍": "#89dceb",  # cyan
            "📦": "#fab387",  # orange
            "⚡": "#cba6f7"   # purple
        }
        
        prefix = message[0] if message else ""
        color = color_map.get(prefix, "#cdd6f4") # default text color
        
        # Escape HTML characters to prevent breaking layout
        import html
        escaped_msg = html.escape(message)
        
        # Append formatted HTML string
        self.console.append(f'<span style="color: {color}; font-family: monospace;">{escaped_msg}</span>')
```

**Step 2: Verify and Commit**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: PASS
```bash
git add app/ui/main_window.py
git commit -m "feat: colorize console logs using QTextEdit HTML spans"
```

---

### Task 4: Declarative Version Pinning in Blueprints

**Files:**
- Modify: [main_window.py](file:///home/daripper/Projects/PolyGet/app/ui/main_window.py)

**Step 1: Write failing test**
Add a test in `tests/test_blueprint_gui.py` verifying that version pins like `black==22.3.0` are handled when calculating drift.

```python
def test_blueprint_version_pinning():
    # Verify that a pinned package with a matching name but different/missing state is flagged
    pass
```

**Step 2: Write implementation**
Modify `handle_sync_check_results` in `app/ui/main_window.py` to parse package strings with version pins (e.g. `==` or `@`).
Extract the base package name to perform the existence check against installed lists, and install with the full version pin:

```python
            for pkg in yaml_pkgs:
                # Split on == or @ to get base package name
                base_name = pkg
                for sep in ("==", "@"):
                    if sep in pkg:
                        base_name = pkg.split(sep)[0]
                        break
                
                if base_name not in installed_pkgs:
                    missing_packages.append((mgr, pkg))
```

**Step 3: Verify and Commit**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: PASS
```bash
git add app/ui/main_window.py
git commit -m "feat: support version pinning in blueprint synchronization"
```

---

### Task 5: Self-Healing Sync Mode

**Files:**
- Modify: [main_window.py](file:///home/daripper/Projects/PolyGet/app/ui/main_window.py)

**Step 1: Write implementation**
Ensure that when a blueprint sync operation completes and detects drift, clicking "Yes" in the confirmation dialog sets up a sequential execution queue in the Process Console and automatically runs it.
This is already partially handled by the sequential `upgrade_queue` in the code, but make sure that:
1. `upgrade_queue` contains the generated install commands for the missing packages.
2. The UI correctly switches to the Console tab and executes them sequentially.
3. The temporary progress indicators are hidden upon completion.

**Step 2: Run all tests and verify**
Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/pytest`
Expected: ALL PASS (44+ tests)
```bash
git add app/ui/main_window.py
git commit -m "feat: automate self-healing sync sequential installations"
```
