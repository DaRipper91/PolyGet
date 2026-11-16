import sys
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton
import app.core.settings_store as settings_store
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def mock_window(qapp, tmp_path, monkeypatch):
    store = settings_store.SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(settings_store, "_settings_instance", store)

    with patch("app.ui.main_window.MainWindow.scan_all"), \
         patch("app.ui.main_window.discover_managers", return_value=[]):
        win = MainWindow()
        win.populate_settings_page()
        yield win, store


def test_font_controls_exist_and_initial_state(mock_window):
    win, store = mock_window
    combo = win.findChild(QComboBox, "font-size-combo")
    assert combo is not None, "Font size QComboBox should exist"
    assert combo.currentData() == 0
    assert combo.currentText() == "Default (13 px)"

    arrow_buttons = [btn for btn in win.findChildren(QPushButton, "btn-font-arrow")]
    assert len(arrow_buttons) == 2, "Should have 2 boxed arrow buttons (down and up)"
    assert any(btn.text() == "▼" for btn in arrow_buttons)
    assert any(btn.text() == "▲" for btn in arrow_buttons)


def test_font_combo_selection_updates_settings(mock_window):
    win, store = mock_window
    combo = win.findChild(QComboBox, "font-size-combo")
    idx = combo.findData(16)
    assert idx >= 0
    combo.setCurrentIndex(idx)

    assert store.get("ui.font_size") == 16
    assert win.ui_font_size == 16


def test_font_arrow_up_and_down_buttons(mock_window):
    win, store = mock_window
    combo = win.findChild(QComboBox, "font-size-combo")
    btn_down = [b for b in win.findChildren(QPushButton, "btn-font-arrow") if b.text() == "▼"][0]
    btn_up = [b for b in win.findChildren(QPushButton, "btn-font-arrow") if b.text() == "▲"][0]

    # Start at default (0)
    store.set("ui.font_size", 0)
    combo.setCurrentIndex(combo.findData(0))

    # Clicking UP from default (13px effective) should increment to 14px
    btn_up.click()
    assert store.get("ui.font_size") == 14
    assert combo.currentData() == 14

    # Clicking UP again -> 15px
    btn_up.click()
    assert store.get("ui.font_size") == 15
    assert combo.currentData() == 15

    # Clicking DOWN -> 14px
    btn_down.click()
    assert store.get("ui.font_size") == 14
    assert combo.currentData() == 14

    # Step down towards default
    store.set("ui.font_size", 10)
    combo.setCurrentIndex(combo.findData(10))
    btn_down.click()
    assert store.get("ui.font_size") == 9

    btn_down.click()
    # Below 9 resets to 0 (default)
    assert store.get("ui.font_size") == 0
    assert combo.currentData() == 0
    assert combo.currentText() == "Default (13 px)"
