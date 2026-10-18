import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtGui import QIcon, QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ICONS = Path(__file__).resolve().parent.parent / "assets" / "icons"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.mark.parametrize("name", ["polyget.svg", "polyget-small.svg", "polyget-symbolic.svg"])
def test_icon_sources_parse(qapp, name):
    assert QSvgRenderer(str(ICONS / name)).isValid()


def test_symbolic_icon_is_recolourable():
    """Panels recolour fills tagged ColorScheme-Text / currentColor; strokes or hard-coded
    colours would stay dark on a dark panel."""
    text = (ICONS / "polyget-symbolic.svg").read_text()
    assert 'class="ColorScheme-Text"' in text and 'fill="currentColor"' in text
    assert "stroke" not in text.split("-->", 1)[1]
    body = text.split("</style>", 1)[1]
    assert "#" not in body  # no hard-coded colours outside the scheme stylesheet


@pytest.mark.parametrize("size", [16, 22, 24, 32, 48, 64, 128, 256, 512])
def test_rendered_pngs_exist_at_their_size(qapp, size):
    image = QImage(str(ICONS / f"polyget-{size}.png"))
    assert (image.width(), image.height()) == (size, size)


def test_tray_prefers_the_installed_symbolic_icon(qapp):
    from app.ui.icons import tray_icon
    themed = QIcon(str(ICONS / "polyget-updates-symbolic.svg"))
    with patch("app.ui.icons.QIcon.hasThemeIcon", side_effect=lambda name: name == "polyget-updates-symbolic"), \
            patch("app.ui.icons.QIcon.fromTheme", return_value=themed) as from_theme:
        assert tray_icon("updates").cacheKey() == themed.cacheKey()
    from_theme.assert_called_once_with("polyget-updates-symbolic")


@pytest.mark.parametrize("state", ["idle", "updates", "updating", "error"])
def test_tray_states_render_from_the_repo_when_not_installed(qapp, state):
    from app.ui.icons import tray_icon
    with patch("app.ui.icons.QIcon.hasThemeIcon", return_value=False):
        icon = tray_icon(state, dark_panel=True)
    assert not icon.isNull() and not icon.pixmap(22, 22).isNull()


@pytest.mark.parametrize("name", ["polyget-updates-symbolic.svg", "polyget-updating-symbolic.svg",
                                  "polyget-error-symbolic.svg"])
def test_state_icons_parse_and_recolour(qapp, name):
    text = (ICONS / name).read_text()
    assert QSvgRenderer(str(ICONS / name)).isValid()
    assert 'class="ColorScheme-Text"' in text and "stroke" not in text.split("-->", 1)[1]


def test_app_icon_takes_the_themes_brand_colour(qapp):
    from app.ui import themes
    from app.ui.icons import app_icon
    try:
        themes.set_active("gruvbox-dark")
        img = app_icon().pixmap(128, 128).toImage()
        arrow = img.pixelColor(64, 50).name()  # middle of the Confluence mark's update arrow
        assert arrow == themes.THEMES["gruvbox-dark"].roles["brand"] == "#fabd2f"
    finally:
        themes.set_active("mocha")
