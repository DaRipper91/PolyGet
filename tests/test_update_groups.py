import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from app.core.manager import PackageManager
from app.ui.main_window import MainWindow, UpdateItemWidget
from app.ui.updates_view import ManagerGroupHeader


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _mgr(name, upgrade_cmd):
    m = MagicMock(spec=PackageManager)
    m.name = name
    m.category = "System"
    m.get_upgrade_command.return_value = upgrade_cmd
    return m


@pytest.fixture
def window(qapp):
    with patch("app.ui.main_window.MainWindow.scan_all"):
        w = MainWindow()
    w.managers = {"DNF": _mgr("DNF", ["pkexec", "dnf", "upgrade", "-y"]),
                  "NPM": _mgr("NPM", ["npm", "update", "-g"]),
                  "Cargo": _mgr("Cargo", ["cargo", "install"]),
                  "Pipx": _mgr("Pipx", ["pipx", "upgrade"])}
    return w


def _rows(window):
    return [window.updates_list.itemWidget(window.updates_list.item(i))
            for i in range(window.updates_list.count())]


def _scan(window):
    window.handle_scan_results("DNF", [{"name": "firefox", "current": "131", "new": "132"},
                                       {"name": "mesa", "current": "24.1", "new": "24.2"}])
    window.handle_scan_results("NPM", [{"name": "typescript", "current": "5.5", "new": "5.6"}])
    window.handle_scan_results("Pipx", [])
    window.handle_scan_error("Cargo", "cargo: registry unreachable")


def test_updates_are_grouped_under_manager_headers(window):
    _scan(window)
    rows = _rows(window)
    headers = [r for r in rows if isinstance(r, ManagerGroupHeader)]
    assert [h.manager for h in headers] == ["DNF", "NPM", "Cargo"]
    assert isinstance(rows[1], UpdateItemWidget) and rows[1].manager_name == "DNF"
    assert "Pipx" in rows[-1].text()  # up-to-date managers fold into the footer


def test_failed_manager_header_offers_retry_with_the_error(window):
    _scan(window)
    cargo = next(r for r in _rows(window) if isinstance(r, ManagerGroupHeader) and r.manager == "Cargo")
    assert cargo.state_label.text() == "scan failed"
    assert cargo.btn_retry is not None and "registry unreachable" in cargo.btn_retry.toolTip()
    dnf = next(r for r in _rows(window) if isinstance(r, ManagerGroupHeader) and r.manager == "DNF")
    assert dnf.btn_retry is None


def test_admin_warning_only_on_elevated_managers(window):
    _scan(window)
    headers = {r.manager: r for r in _rows(window) if isinstance(r, ManagerGroupHeader)}
    def admin_text(h):
        return [c.text() for c in h.findChildren(type(h.state_label)) if c.objectName() == "group-admin"]
    assert admin_text(headers["DNF"]) == ["Needs admin password"]
    assert admin_text(headers["NPM"]) == []


def test_retry_rescans_only_that_manager(window):
    _scan(window)
    with patch.object(QThread, "start"):
        window.rescan_manager("Cargo")
    worker = window.active_workers[-1]
    assert [m.name for m in worker.managers] == ["Cargo"]
    assert window.manager_scan_state["Cargo"] == "scanning" and "Cargo" not in window.scan_errors

    window.handle_scan_results("Cargo", [{"name": "ripgrep", "current": "14.1.0", "new": "14.1.1"}],
                               window.scan_generation)
    window._finish_rescan()
    assert window.manager_scan_state["Cargo"] == "done"
    assert window.updates_cache["DNF"][0]["name"] == "firefox"  # others untouched
    assert "ripgrep" in window.selected_updates["Cargo"]


def test_retry_is_ignored_while_a_full_scan_runs(window):
    _scan(window)
    window.scan_in_progress = True
    with patch.object(QThread, "start"):
        window.rescan_manager("Cargo")
    assert window.active_workers == []


def test_group_checkbox_selects_all_then_none(window):
    _scan(window)
    window.selected_updates["DNF"] = {"firefox"}
    window.toggle_manager_selection("DNF")
    assert window.selected_updates["DNF"] == {"firefox", "mesa"}
    window.toggle_manager_selection("DNF")
    assert window.selected_updates["DNF"] == set()


def test_controls_count_selection_and_warn_about_admin(window):
    _scan(window)  # DNF 2 (pkexec) + NPM 1, all auto-selected
    assert window.chk_select_all.text() == "3 of 3"
    assert window.btn_update_selected.text() == "Update 3"
    bar = window.selection_bar
    assert not bar.isHidden()
    assert bar.admin.text() == "2 need your admin password (DNF)"
    assert window.act_update_user.text() == "Only user-level, no password (1)"


def test_nothing_ticked_hides_the_bar_and_primary_updates_all(window):
    _scan(window)
    window.deselect_all_updates()
    assert window.selection_bar.isHidden()
    assert window.chk_select_all.text() == "0 of 3"
    assert window.btn_update_selected.text() == "Update all (3)"
    assert window.btn_update_selected.isEnabled()
    with patch.object(MainWindow, "start_batch_upgrade") as start:
        window.run_primary_update()
    assert start.call_args.kwargs["targets"] == {
        "DNF": ["firefox", "mesa"], "NPM": ["typescript"], "Pipx": [], "Cargo": []}


def test_user_level_upgrade_skips_password_managers(window):
    _scan(window)
    with patch.object(MainWindow, "start_batch_upgrade") as start:
        window.update_user_level()
    assert start.call_args.kwargs["targets"] == {"NPM": ["typescript"]}


def test_select_all_checkbox_toggles_everything(window):
    _scan(window)
    window.selected_updates["DNF"] = {"firefox"}
    window.refresh_update_controls()
    assert window.chk_select_all.checkState().name == "PartiallyChecked"
    window.toggle_all_selection()
    assert window.chk_select_all.text() == "3 of 3"
    window.toggle_all_selection()
    assert window.chk_select_all.text() == "0 of 3"


def test_row_tick_updates_bar_and_group_header_without_rebuild(window):
    _scan(window)
    window.on_item_selection_changed(False, "firefox", "DNF")
    assert window.selection_bar.admin.text() == "1 needs your admin password (DNF)"
    dnf = next(r for r in _rows(window) if isinstance(r, ManagerGroupHeader) and r.manager == "DNF")
    assert dnf.checkbox.checkState().name == "PartiallyChecked"
