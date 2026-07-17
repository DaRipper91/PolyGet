import sys
import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    """Fixture to initialize QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@patch("app.ui.main_window.MainWindow.scan_all")
def test_updates_badge_hidden_on_construction(mock_scan, qapp):
    """Test the pending-updates badge starts hidden with no scan results yet."""
    window = MainWindow()
    assert window.nav_updates_badge.isVisible() is False


@patch("app.ui.main_window.MainWindow.scan_all")
def test_updates_badge_shows_total_across_managers(mock_scan, qapp):
    """Test the badge reflects the summed count across every manager in updates_cache."""
    window = MainWindow()
    window.updates_cache = {
        "NPM": [{"name": "a"}, {"name": "b"}],
        "Cargo": [{"name": "c"}],
    }

    window.update_updates_badge()

    # isVisible() also depends on ancestor visibility, which is False here since the window is
    # never shown — isHidden() reflects only the widget's own explicit setVisible() flag.
    assert window.nav_updates_badge.isHidden() is False
    assert window.nav_updates_badge.text() == "3"


@patch("app.ui.main_window.MainWindow.scan_all")
def test_updates_badge_hides_when_nothing_outdated(mock_scan, qapp):
    """Test the badge hides again once every manager reports zero updates."""
    window = MainWindow()
    window.updates_cache = {"NPM": [{"name": "a"}]}
    window.update_updates_badge()
    assert window.nav_updates_badge.isHidden() is False

    window.updates_cache = {"NPM": [], "Cargo": []}
    window.update_updates_badge()

    assert window.nav_updates_badge.isHidden() is True


@patch("app.ui.main_window.MainWindow.scan_all")
def test_nav_updates_row_matches_native_row_height(mock_scan, qapp):
    """Test the widget-based "System Updates" row is sized like the plain-text nav rows.

    Regression guard: setItemWidget()'d items don't get the ::item padding/margin QSS box
    applied to their sizeHint automatically the way plain-text items do — see the comment in
    _create_nav_row(). If this ever drifts, the row silently collapses to its bare content
    height (a handful of px) instead of matching the other rows.
    """
    window = MainWindow()
    updates_item = window.nav_list.item(0)
    store_item = window.nav_list.item(1)

    assert window.nav_list.itemWidget(updates_item) is not None
    assert updates_item.sizeHint() == store_item.sizeHint()


@patch("app.ui.main_window.MainWindow.scan_all")
def test_change_page_styles_updates_row_as_selected_only_on_row_zero(mock_scan, qapp):
    """Test the manual selected-state styling toggles as nav_list selection changes."""
    window = MainWindow()

    window.change_page(1)
    assert "#89b4fa" not in window.nav_updates_label.styleSheet()

    window.change_page(0)
    assert "#89b4fa" in window.nav_updates_label.styleSheet()
