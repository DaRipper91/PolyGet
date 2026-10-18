"""Alternative sidebar headers and navigation views, switchable from Settings.

The main window's ``nav_list`` stays the single source of truth for which page is shown;
the views here only mirror it. Each nav view emits ``page_selected`` when clicked and is
told about page changes through ``set_current``, so every existing
``nav_list.setCurrentRow(PAGE_X)`` call keeps working whichever style is active.
"""

import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from app.ui.themes import themed

HEADER_STYLES = {
    "banner": "Classic banner",
    "brand": "Name and system info",
    "status": "Status card",
}
NAV_STYLES = {
    "list": "Classic list",
    "grouped": "Grouped sections",
    "rail": "Icon rail",
}
DEFAULT_HEADER_STYLE = "banner"
DEFAULT_NAV_STYLE = "list"

# Catppuccin Mocha accents, one per manager so the status bar's segments are told apart.
MANAGER_TONE = {
    "DNF": "#89b4fa", "Pacman": "#74c7ec", "AUR": "#89dceb", "APT": "#b4befe",
    "Flatpak": "#94e2d5", "Snap": "#a6e3a1", "Nix": "#7287fd", "Homebrew": "#f9e2af",
    "NPM": "#f38ba8", "pnpm": "#eba0ac", "Yarn": "#74c7ec", "Bun": "#f5e0dc", "Deno": "#a6e3a1",
    "Cargo": "#fab387", "Pipx": "#f9e2af", "uv": "#cba6f7", "Poetry": "#89dceb",
    "Conda": "#a6e3a1", "RubyGems": "#eba0ac", "Bundler": "#f2cdcd", "Go": "#89dceb",
}
_FALLBACK_TONES = ("#f5c2e7", "#cba6f7", "#94e2d5", "#fab387", "#89b4fa", "#a6e3a1")


def manager_tone(name: str) -> str:
    """Return a stable accent color for a manager, falling back to a palette slot."""
    if name in MANAGER_TONE:
        return MANAGER_TONE[name]
    return _FALLBACK_TONES[sum(map(ord, name)) % len(_FALLBACK_TONES)]


@dataclass(frozen=True)
class NavEntry:
    page: int
    label: str
    short: str  # rail label, kept to one short word
    icon: str  # freedesktop icon-theme name


def _app_icon() -> QIcon:
    icon = QApplication.windowIcon()
    return icon if not icon.isNull() else QIcon.fromTheme("system-software-update")


def _badge_label() -> QLabel:
    badge = QLabel("")
    badge.setObjectName("nav-badge")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setVisible(False)
    return badge


class _NavView(QWidget):
    """Shared button bookkeeping for the grouped and rail views."""

    page_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.page_selected.emit)
        self._badges: dict[int, QLabel] = {}

    def _register(self, button, entry: NavEntry, badge: QLabel) -> None:
        button.setCheckable(True)
        button.setAccessibleName(entry.label)
        self._group.addButton(button, entry.page)
        self._badges[entry.page] = badge

    def set_current(self, page: int) -> None:
        button = self._group.button(page)
        if button is not None:
            button.setChecked(True)

    def current(self) -> int:
        return self._group.checkedId()

    def set_badge(self, page: int, text: str, style: str) -> None:
        """Show ``text`` in the page's badge, or hide it when ``text`` is empty."""
        badge = self._badges.get(page)
        if badge is None:
            return
        badge.setText(text)
        badge.setStyleSheet(style)
        badge.setVisible(bool(text))


class GroupedNav(_NavView):
    """Pages under small section headings, with a footer group pinned to the bottom."""

    def __init__(self, groups: list[tuple[str, list[NavEntry]]], footer: list[NavEntry],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("nav-grouped")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for title, entries in groups:
            heading = QLabel(title.upper())
            heading.setObjectName("nav-section")
            layout.addWidget(heading)
            for entry in entries:
                layout.addWidget(self._button(entry))
        layout.addStretch()
        for entry in footer:
            layout.addWidget(self._button(entry))

    def _button(self, entry: NavEntry) -> QPushButton:
        button = QPushButton(QIcon.fromTheme(entry.icon), entry.label)
        button.setObjectName("nav-button")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        badge = _badge_label()
        row = QHBoxLayout(button)
        row.setContentsMargins(0, 0, 10, 0)
        row.addStretch()
        row.addWidget(badge)
        self._register(button, entry, badge)
        return button


class RailNav(_NavView):
    """A narrow strip of icon-over-label buttons with count bubbles on the icons."""

    WIDTH = 84

    def __init__(self, entries: list[NavEntry], footer: list[NavEntry],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("nav-rail")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for entry in entries:
            layout.addWidget(self._button(entry), 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        for entry in footer:
            layout.addWidget(self._button(entry), 0, Qt.AlignmentFlag.AlignHCenter)

    def _button(self, entry: NavEntry) -> QWidget:
        cell = QWidget()
        grid = QGridLayout(cell)
        grid.setContentsMargins(0, 0, 0, 0)
        button = QToolButton()
        button.setObjectName("rail-button")
        button.setIcon(QIcon.fromTheme(entry.icon))
        button.setText(entry.short)
        button.setToolTip(entry.label)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setFixedWidth(self.WIDTH - 12)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        badge = _badge_label()
        badge.setFixedHeight(18)  # the 9px badge radius needs >= 18px or Qt draws it square
        # Both widgets share cell (0, 0); the badge sits over the button's top-right corner.
        grid.addWidget(button, 0, 0)
        grid.addWidget(badge, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self._register(button, entry, badge)
        return cell


class BannerHeader(QWidget):
    """The original gradient "POLYGET" banner."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebar-banner")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(4)
        title = QLabel("POLYGET")
        title.setObjectName("banner-title")
        subtitle = QLabel("Unified Software Hub")
        subtitle.setObjectName("banner-subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)


class BrandHeader(QWidget):
    """App icon, name, and a live subtitle such as "Fedora Linux 41 · 5 managers"."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("brand-header")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(36, 36)
        self.icon.setPixmap(_app_icon().pixmap(36, 36))
        layout.addWidget(self.icon)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel("PolyGet")
        name.setObjectName("brand-name")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("brand-subtitle")
        text.addWidget(name)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


class StatusCard(QFrame):
    """Pending-update count, a per-manager bar, and a slot for the "Check for Updates" button."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("status-card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(26, 26)
        self.icon.setPixmap(_app_icon().pixmap(26, 26))
        top.addWidget(self.icon)
        name = QLabel("PolyGet")
        name.setObjectName("brand-name")
        top.addWidget(name, 1)
        layout.addLayout(top)

        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        self.count = QLabel("–")
        self.count.setObjectName("status-count")
        self.count_caption = QLabel("")
        self.count_caption.setObjectName("brand-subtitle")
        count_row.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        count_row.addWidget(self.count_caption, 1, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(count_row)

        self.bar = QWidget()
        self.bar.setObjectName("status-bar")
        self.bar.setFixedHeight(8)
        self._bar_layout = QHBoxLayout(self.bar)
        self._bar_layout.setContentsMargins(0, 0, 0, 0)
        self._bar_layout.setSpacing(2)
        layout.addWidget(self.bar)

        self.legend = QLabel("")
        self.legend.setObjectName("brand-subtitle")
        self.legend.setWordWrap(True)
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.legend)

        self.button_slot = QVBoxLayout()
        self.button_slot.setSpacing(0)
        layout.addLayout(self.button_slot)
        self.checked = QLabel("")
        self.checked.setObjectName("status-checked")
        layout.addWidget(self.checked)

    def update_status(self, counts: dict[str, int], scanning: bool, checked_at: float | None) -> None:
        """Redraw from per-manager pending counts; managers with nothing pending are left out."""
        pending = {name: n for name, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n > 0}
        total = sum(pending.values())
        self.count.setText(str(total) if (total or not scanning) else "…")
        if scanning and not total:
            self.count_caption.setText("checking…")
        else:
            self.count_caption.setText("update waiting" if total == 1 else "updates waiting")

        while self._bar_layout.count():
            item = self._bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for name, n in pending.items():
            segment = QFrame()
            segment.setStyleSheet(f"background-color: {manager_tone(name)}; border-radius: 3px;")
            self._bar_layout.addWidget(segment, n)
        self.bar.setVisible(bool(pending))
        self.legend.setText("   ".join(
            f'<span style="color: {themed(manager_tone(name))};">●</span> {name} {n}'
            for name, n in pending.items()))
        self.legend.setVisible(bool(pending))

        if scanning:
            self.checked.setText("Scanning now…")
        elif checked_at is None:
            self.checked.setText("Not checked yet")
        else:
            self.checked.setText(f"Checked {time_ago(checked_at)}")


def time_ago(ts: float) -> str:
    minutes = int((time.time() - ts) // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 24 else f"{hours // 24} d ago"
