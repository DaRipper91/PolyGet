import sys
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

import app.core.settings_store as settings_store
from app.ui.main_window import MainWindow, PAGE_HISTORY, PAGE_UPDATES, PAGE_VERSION_CHECK


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def settings(tmp_path, monkeypatch):
    store = settings_store.SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(settings_store, "_settings_instance", store)
    return store


@pytest.fixture
def window(qapp, settings):
    with patch("app.ui.main_window.MainWindow.scan_all"):
        yield MainWindow()


def _style(window, settings, header, nav):
    settings.set("ui.sidebar_header", header)
    settings.set("ui.sidebar_nav", nav)
    window.apply_sidebar_style()


def test_defaults_keep_the_classic_sidebar(window):
    assert window.sidebar_header_style == "banner"
    assert window.sidebar_nav_style == "list"
    assert not window.header_banner.isHidden()
    assert not window.nav_list.isHidden()
    assert window.nav_grouped.isHidden() and window.nav_rail.isHidden()
    assert not window.status_list.isHidden()


def test_unknown_saved_values_fall_back_to_classic(window, settings):
    _style(window, settings, "neon", "carousel")
    assert window.sidebar_header_style == "banner"
    assert window.sidebar_nav_style == "list"


def test_grouped_nav_mirrors_nav_list_both_ways(window, settings):
    _style(window, settings, "brand", "grouped")
    assert window.nav_list.isHidden() and not window.nav_grouped.isHidden()
    assert not window.header_brand.isHidden() and window.header_banner.isHidden()

    window.nav_grouped._group.button(PAGE_HISTORY).click()
    assert window.nav_list.currentRow() == PAGE_HISTORY
    assert window.stacked_widget.currentIndex() == PAGE_HISTORY

    window.nav_list.setCurrentRow(PAGE_UPDATES)  # programmatic switches, as scans/upgrades do
    assert window.nav_grouped.current() == PAGE_UPDATES


def test_badges_reach_the_new_views(window, settings):
    _style(window, settings, "banner", "grouped")
    window.updates_cache = {"NPM": [{"name": "a"}, {"name": "b"}], "Cargo": [{"name": "c"}]}
    window.update_updates_badge()
    window.update_version_check_badge(4)
    assert window.nav_grouped._badges[PAGE_UPDATES].text() == "3"
    assert window.nav_rail._badges[PAGE_VERSION_CHECK].text() == "4"

    window.updates_cache = {}
    window.update_updates_badge()
    assert window.nav_grouped._badges[PAGE_UPDATES].isHidden()


def test_status_card_hosts_the_scan_button_and_replaces_the_status_list(window, settings):
    _style(window, settings, "status", "list")
    assert window.btn_scan.parent() is window.header_status
    assert window.status_list.isHidden()

    window.updates_cache = {"DNF": [{"name": "a"}] * 6, "Flatpak": [{"name": "b"}] * 3, "NPM": []}
    window.refresh_sidebar_status()
    assert window.header_status.count.text() == "9"
    assert "DNF 6" in window.header_status.legend.text()
    assert "NPM" not in window.header_status.legend.text()  # nothing pending, left out

    _style(window, settings, "banner", "list")  # switching back returns the button
    assert window.btn_scan.parent() is window.sidebar_widget
    assert not window.status_list.isHidden()


def test_rail_moves_filter_to_updates_page_and_restores_it(window, settings):
    window.search_bar.setText("fire")
    _style(window, settings, "status", "rail")
    assert window.search_bar.parent() is not window.sidebar_widget
    assert window.search_bar.text() == "fire"
    assert window.btn_scan.text() == "" and window.btn_scan.toolTip() == "Check for Updates"
    assert window.header_status.isHidden()  # rail ignores the header choice
    assert window.sidebar_widget.maximumWidth() == window.sidebar_widget.minimumWidth()

    _style(window, settings, "banner", "list")
    assert window.search_bar.parent() is window.sidebar_widget
    assert window.btn_scan.text() == "Check for Updates"
    assert window.sidebar_widget.maximumWidth() > 10000


def test_settings_page_combos_save_and_apply(window, settings):
    from PySide6.QtWidgets import QComboBox
    window.populate_settings_page()
    combos = {c.accessibleName(): c for c in window.findChildren(QComboBox) if c.accessibleName()}
    combos["Navigation"].setCurrentIndex(combos["Navigation"].findData("rail"))
    assert settings.get("ui.sidebar_nav") == "rail"
    assert window.sidebar_nav_style == "rail"
    assert not combos["Header"].isEnabled()
