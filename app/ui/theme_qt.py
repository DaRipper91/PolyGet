"""Apply app/ui/themes.py to Qt widgets.

Widgets set their own stylesheets in Mocha colours all over the GUI. Rather than touch each
call, an application-wide event filter catches every stylesheet as it's applied (Polish /
StyleChange) and rewrites it for the active theme, remembering the Mocha source so a later
theme switch can re-theme widgets that already exist.
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from app.ui import themes

_SRC = "_polyget_qss_src"   # the stylesheet as the code set it (Mocha colours)
_OUT = "_polyget_qss_out"   # what we last applied, to tell our own writes from new ones


class ThemeFilter(QObject):
    """Rewrites each widget's stylesheet for the active theme as Qt styles it."""

    _EVENTS = (QEvent.Type.Polish, QEvent.Type.StyleChange)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt's name
        if event.type() in self._EVENTS and isinstance(obj, QWidget):
            ss = obj.styleSheet()
            if ss and ss != obj.property(_OUT):
                self._apply(obj, ss)
        return False

    @staticmethod
    def _apply(widget: QWidget, source: str) -> None:
        out = themes.themed(source)
        widget.setProperty(_SRC, source)
        widget.setProperty(_OUT, out)
        if widget.styleSheet() != out:  # also undoes an earlier theme when returning to Mocha
            widget.setStyleSheet(out)

    def retheme_all(self) -> None:
        """After a theme change: re-theme every widget from the source it was given."""
        for widget in QApplication.allWidgets():
            source = widget.property(_SRC)
            if source:
                self._apply(widget, source)


_filter: ThemeFilter | None = None


def install() -> ThemeFilter:
    """Install the filter on the application once; returns it."""
    global _filter
    if _filter is None:
        _filter = ThemeFilter(QApplication.instance())
        QApplication.instance().installEventFilter(_filter)
    return _filter


def system_is_dark() -> bool:
    """Whether the desktop asks for a dark colour scheme (Qt 6.5+), else judge by the palette."""
    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    window = QGuiApplication.palette().color(QPalette.ColorRole.Window)
    return window.lightness() < 128
