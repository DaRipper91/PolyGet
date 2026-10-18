"""PolyGet's own icons: the theme-tinted app icon and the tray icon's states."""

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.ui import themes

ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"

# Tray state -> icon-theme name (and file under assets/icons/ with .svg).
TRAY_STATES = {
    "idle": "polyget-symbolic",
    "updates": "polyget-updates-symbolic",
    "updating": "polyget-updating-symbolic",
    "error": "polyget-error-symbolic",
}
_SYMBOLIC_INK = "#232629"  # the ColorScheme-Text default in the symbolic SVGs


def _render(svg_text: str, sizes: tuple[int, ...], icon: QIcon | None = None) -> QIcon:
    icon = icon or QIcon()
    renderer = QSvgRenderer(QByteArray(svg_text.encode()))
    for size in sizes:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


_SUN = "#cba6f7"  # the icon's sun, drawn in Mocha mauve
_SUN_MARK = "#b0b0b1"  # placeholder while theming; no theme maps it


def _brand_themed(svg_text: str) -> str:
    """Theme the icon, painting the sun in the theme's brand colour rather than its mauve."""
    marked = svg_text.replace(_SUN, _SUN_MARK)
    return themes.themed(marked, force=True).replace(_SUN_MARK, themes.active().role("brand"))


def app_icon() -> QIcon:
    """polyget.svg in the active theme's colours (its brand colour for the sun), with the
    simplified drawing at 16/32px where the stripes would blur."""
    big, small = (_brand_themed((ICON_DIR / name).read_text(encoding="utf-8"))
                  for name in ("polyget.svg", "polyget-small.svg"))
    icon = _render(small, (16, 32))
    return _render(big, (24, 48, 64, 128, 256), icon)


def tray_icon(state: str = "idle", dark_panel: bool = True) -> QIcon:
    """The one-colour tray icon for `state` ("idle", "updates", "updating", "error").

    Installed icons (scripts/install-desktop.sh) are loaded by name, so Plasma/GNOME recolour
    them to the panel. Otherwise the repo's copy is drawn in a fixed colour for a dark or light
    panel, keeping its dot/warning colours.
    """
    name = TRAY_STATES.get(state, TRAY_STATES["idle"])
    if QIcon.hasThemeIcon(name):
        return QIcon.fromTheme(name)
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon.fromTheme("polyget")
    ink = "#eff1f5" if dark_panel else _SYMBOLIC_INK
    return _render(path.read_text(encoding="utf-8").replace(_SYMBOLIC_INK, ink), (16, 22, 24, 32, 44, 64))
