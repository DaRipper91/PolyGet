"""Widgets for the Updates page: per-manager group headers and the selection bar."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QWidget

from app.ui.sidebar import time_ago, manager_tone


class ManagerGroupHeader(QWidget):
    """Header row above one manager's updates: state, admin warning, select-all and Retry."""

    toggle_requested = Signal(str)  # manager name: select all of its updates, or none if all are
    retry_requested = Signal(str)   # manager name: rescan just this manager

    def __init__(self, manager: str, *, pending: int, selected: int, state: str,
                 error: str = "", needs_admin: bool = False, checked_at: float | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self.setObjectName("group-header")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # paint the QSS box
        failed = state == "failed"
        self.setProperty("failed", failed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self.checkbox = QCheckBox()
        self.checkbox.setAccessibleName(f"Select all {manager} updates")
        self.checkbox.setTristate(True)
        self.checkbox.setCheckState(
            Qt.CheckState.Unchecked if selected == 0 else
            Qt.CheckState.Checked if selected >= pending else Qt.CheckState.PartiallyChecked)
        self.checkbox.setEnabled(pending > 0)
        # A click must mean "all" or "none", never cycle into the partial state by itself.
        self.checkbox.clicked.connect(lambda _=False: self.toggle_requested.emit(self.manager))
        layout.addWidget(self.checkbox)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background-color: {manager_tone(manager)}; border-radius: 5px;")
        layout.addWidget(dot)

        name = QLabel(manager)
        name.setObjectName("group-name")
        layout.addWidget(name)

        if failed:
            text = "scan failed"
        elif state == "scanning":
            text = "scanning…"
        else:
            text = f"{pending} update{'' if pending == 1 else 's'}"
        self.state_label = QLabel(text)
        self.state_label.setObjectName("group-state-failed" if failed else "group-state")
        if error:
            self.state_label.setToolTip(error)
        layout.addWidget(self.state_label)
        layout.addStretch()

        if needs_admin and pending:
            admin = QLabel("Needs admin password")
            admin.setObjectName("group-admin")
            admin.setToolTip(f"{manager} upgrades run through pkexec, which asks for your password")
            layout.addWidget(admin)
        if checked_at is not None and state == "done":
            when = QLabel(time_ago(checked_at))
            when.setObjectName("group-when")
            layout.addWidget(when)
        self.btn_retry = None
        if failed:
            self.btn_retry = QPushButton("Retry")
            self.btn_retry.setObjectName("group-retry")
            self.btn_retry.setAccessibleName(f"Retry {manager} scan")
            self.btn_retry.setToolTip(error or f"Scan {manager} again")
            self.btn_retry.clicked.connect(lambda: self.retry_requested.emit(self.manager))
            layout.addWidget(self.btn_retry)
