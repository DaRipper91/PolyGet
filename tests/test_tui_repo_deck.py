import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.ui.tui import PolyGetTuiApp, find_repo_deck_cmd


def test_find_repo_deck_cmd_from_path(monkeypatch):
    monkeypatch.setattr("app.ui.tui.shutil.which", lambda name: "/custom/bin/asahi-deck")
    monkeypatch.setattr("app.ui.tui.os.access", lambda path, mode: True)
    cmd = find_repo_deck_cmd()
    assert cmd == ["/custom/bin/asahi-deck"]


def test_find_repo_deck_cmd_fallback_py(monkeypatch):
    monkeypatch.setattr("app.ui.tui.shutil.which", lambda name: None)

    def fake_is_file(self):
        return "repo-config-deck" in str(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    monkeypatch.setattr("app.ui.tui.os.access", lambda path, mode: True)

    cmd = find_repo_deck_cmd()
    assert cmd is not None
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("asahi-deck.py")


def test_find_repo_deck_cmd_not_found(monkeypatch):
    monkeypatch.setattr("app.ui.tui.shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    cmd = find_repo_deck_cmd()
    assert cmd is None


def test_action_open_repo_deck_not_found_notifies():
    async def run_test():
        with patch("app.ui.tui.discover_managers", return_value=[]), \
             patch("app.ui.tui.shutil.which", return_value=None), \
             patch("app.ui.tui.find_repo_deck_cmd", return_value=None):
            app = PolyGetTuiApp()
            async with app.run_test():
                with patch.object(app, "notify") as mock_notify, \
                     patch("app.ui.tui.subprocess.run") as mock_run:
                    await app.action_open_repo_deck()
                    mock_notify.assert_called_once()
                    assert "not found" in mock_notify.call_args[0][0].lower()
                    mock_run.assert_not_called()

    asyncio.run(run_test())


def test_action_open_repo_deck_suspends_executes_and_rescans():
    async def run_test():
        with patch("app.ui.tui.discover_managers", return_value=[]), \
             patch("app.ui.tui.shutil.which", return_value=None), \
             patch("app.ui.tui.find_repo_deck_cmd", return_value=["/usr/bin/asahi-deck"]):
            app = PolyGetTuiApp()
            async with app.run_test():
                suspend_called = []

                class FakeSuspendContext:
                    def __enter__(self):
                        suspend_called.append("enter")
                        return self

                    def __exit__(self, exc_type, exc_val, exc_tb):
                        suspend_called.append("exit")

                with patch.object(app, "suspend", side_effect=FakeSuspendContext), \
                     patch("app.ui.tui.subprocess.run") as mock_run, \
                     patch.object(app, "action_rescan_managers", new_callable=AsyncMock) as mock_rescan, \
                     patch.object(app, "notify") as mock_notify:
                    await app.action_open_repo_deck()
                    assert suspend_called == ["enter", "exit"]
                    mock_run.assert_called_once_with(["/usr/bin/asahi-deck"], check=False)
                    mock_rescan.assert_awaited_once()
                    assert mock_notify.call_count >= 1

    asyncio.run(run_test())


def test_action_open_repo_deck_handles_subprocess_error():
    async def run_test():
        with patch("app.ui.tui.discover_managers", return_value=[]), \
             patch("app.ui.tui.shutil.which", return_value=None), \
             patch("app.ui.tui.find_repo_deck_cmd", return_value=["/usr/bin/asahi-deck"]):
            app = PolyGetTuiApp()
            async with app.run_test():
                with patch("app.ui.tui.subprocess.run", side_effect=OSError("Exec error")), \
                     patch.object(app, "notify") as mock_notify:
                    await app.action_open_repo_deck()
                    mock_notify.assert_called_once()
                    assert "Failed to launch" in mock_notify.call_args[0][0]

    asyncio.run(run_test())
