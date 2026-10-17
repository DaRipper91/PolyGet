"""Widgets for the Updates page: per-manager group headers and the selection bar."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

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


class SelectionBar(QFrame):
    """Bar under the update list while anything is ticked: how many, and how many will ask for
    the admin password, before Update is pressed — so pkexec prompts never come as a surprise."""

    clear_requested = Signal()
    update_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("selection-bar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 8, 8)
        layout.setSpacing(14)
        self.count = QLabel("")
        self.count.setObjectName("selection-count")
        layout.addWidget(self.count)
        self.admin = QLabel("")
        self.admin.setObjectName("selection-admin")
        layout.addWidget(self.admin)
        layout.addStretch()
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("selection-clear")
        self.btn_clear.clicked.connect(self.clear_requested.emit)
        layout.addWidget(self.btn_clear)
        self.btn_update = QPushButton("Update")
        self.btn_update.clicked.connect(self.update_requested.emit)
        layout.addWidget(self.btn_update)

    def update_state(self, selected: int, admin: int, admin_managers: list[str]) -> None:
        self.count.setText(f"{selected} selected")
        self.btn_update.setText(f"Update {selected}")
        if admin:
            who = ", ".join(admin_managers)
            self.admin.setText(f"{admin} need{'s' if admin == 1 else ''} your admin password ({who})")
            self.admin.setToolTip(f"{who} upgrades run through pkexec: expect "
                                  f"{len(admin_managers)} password prompt(s), one per manager.")
        else:
            self.admin.setText("No password needed")
            self.admin.setToolTip("")
        self.admin.setProperty("warn", bool(admin))
        self.admin.style().unpolish(self.admin)
        self.admin.style().polish(self.admin)
