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


@pytest.mark.parametrize("size", [16, 32, 48, 64, 128, 256, 512])
def test_rendered_pngs_exist_at_their_size(qapp, size):
    image = QImage(str(ICONS / f"polyget-{size}.png"))
    assert (image.width(), image.height()) == (size, size)


def test_tray_prefers_the_themed_symbolic_icon(qapp):
    from app.ui.main_window import tray_icon
    themed = QIcon(str(ICONS / "polyget-symbolic.svg"))
    with patch("app.ui.main_window.QIcon.fromTheme", side_effect=lambda name, fallback=None:
               themed if name == "polyget-symbolic" else QIcon()):
        assert tray_icon().cacheKey() == themed.cacheKey()
