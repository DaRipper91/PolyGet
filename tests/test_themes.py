import asyncio
import re
import sys
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QLabel

import app.core.settings_store as settings_store
from app.ui import themes
from app.ui.themes import THEMES, contrast, themed


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
    yield store
    themes.set_active(themes.DEFAULT_THEME)


def test_there_are_plenty_of_themes_light_and_dark():
    assert len(THEMES) >= 15
    assert sum(t.light for t in THEMES.values()) >= 4


@pytest.mark.parametrize("key", list(THEMES))
def test_every_theme_is_readable(key):
    r = THEMES[key].roles
    assert contrast(r["text"], r["base"]) >= 4.5
    assert contrast(r["subtext0"], r["base"]) >= 4.0
    assert contrast(r["on_accent"], r["blue"]) >= 3.0
    for accent in ("red", "yellow", "green", "peach", "blue"):
        assert contrast(r[accent], r["base"]) >= 4.5, accent


def test_mocha_is_left_exactly_as_written():
    qss = "QWidget { background: #1e1e2e; color: #cdd6f4; } QLabel { color: #11111b; }"
    assert themed(qss, themes.Active(THEMES["mocha"])) == qss


def test_theming_maps_roles_and_text_on_accent():
    latte = themes.Active(THEMES["latte"])
    out = themed("QPushButton { background-color: #89b4fa; color: #11111b; } "
                 "QWidget#side { background-color: #11111b; }", latte)
    r = THEMES["latte"].roles
    assert f"background-color: {r['blue']}" in out
    assert f"color: {r['on_accent']}" in out           # text on the filled button
    assert f"background-color: {r['crust']}" in out     # crust as a background stays crust
    assert not re.search(r"#(89b4fa|11111b)", out)


def test_tailwind_leftovers_and_tints_are_themed():
    nord = themes.Active(THEMES["nord"])
    out = themed("background-color: #064e3b; color: #6ee7b7;", nord)
    assert "#064e3b" not in out and THEMES["nord"].roles["green"] in out


def test_accent_override_swaps_the_primary_colour():
    a = themes.Active(THEMES["mocha"], accent="pink")
    assert themed("background: #89b4fa;", a) == f"background: {THEMES['mocha'].roles['pink']};"


def test_follow_system_picks_dark_or_light():
    assert themes.resolve("system", True, "nord", "solarized-light") == "nord"
    assert themes.resolve("system", False, "nord", "solarized-light") == "solarized-light"
    assert themes.resolve("not-a-theme", True) == themes.DEFAULT_THEME


def test_widgets_are_themed_live_and_rethemed_on_switch(qapp, settings):
    from app.ui import theme_qt
    from app.ui.main_window import MainWindow
    settings.set("ui.theme", "gruvbox-dark")
    with patch("app.ui.main_window.MainWindow.scan_all"):
        w = MainWindow()
    label = QLabel("x", w)
    label.setStyleSheet("color: #f38ba8;")
    label.ensurePolished()
    assert THEMES["gruvbox-dark"].roles["red"] in label.styleSheet()
    assert THEMES["gruvbox-dark"].roles["base"] in w.styleSheet()

    settings.set("ui.theme", "latte")
    w.apply_appearance()
    assert THEMES["latte"].roles["red"] in label.styleSheet()
    assert THEMES["latte"].roles["base"] in w.styleSheet()

    settings.set("ui.theme", "mocha")
    w.apply_appearance()
    assert label.styleSheet() == "color: #f38ba8;"


def test_system_scheme_change_only_matters_when_following_system(qapp, settings):
    from app.ui.main_window import MainWindow
    with patch("app.ui.main_window.MainWindow.scan_all"):
        w = MainWindow()
    with patch.object(MainWindow, "apply_appearance") as apply:
        w._on_system_scheme_changed()
        assert not apply.called
        settings.set("ui.theme", "system")
        w._on_system_scheme_changed()
        assert apply.called


def test_tui_css_follows_the_theme(settings):
    from app.ui.tui import themed_tui_css
    settings.set("ui.theme", "dracula")
    css = themed_tui_css()
    assert THEMES["dracula"].roles["crust"] in css
    assert "#0d0714" not in css  # the TUI's own purple is mapped too


def test_tui_starts_with_the_themed_css(settings):
    from textual.color import Color
    from app.ui.tui import PolyGetTuiApp
    settings.set("ui.theme", "nord")

    async def run():
        with patch("app.ui.tui.discover_managers", return_value=[]):
            app = PolyGetTuiApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                return app.screen.styles.background
    bg = asyncio.run(run())
    assert bg == Color.parse(THEMES["nord"].roles["crust"])
