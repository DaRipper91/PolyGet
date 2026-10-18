"""Show AUR build scripts (PKGBUILDs) before PolyGet builds them.

AUR packages build from user-submitted scripts that run as you, and PolyGet installs them with
--noconfirm, so this dialog is the one chance to read what will run. A script that couldn't be
fetched can't be reviewed, so the dialog then refuses to proceed with those packages.
"""

import asyncio
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from app.core.manager import PackageManager, describe_error


def has_build_scripts(mgr: PackageManager) -> bool:
    """True when the driver overrides get_build_script (today only the AUR)."""
    impl = getattr(type(mgr), "get_build_script", PackageManager.get_build_script)
    return impl is not PackageManager.get_build_script


class BuildScriptWorker(QThread):
    """Fetch every package's build script concurrently, off the UI thread."""

    # {package: {"url": str, "script": str} | {"error": str}}
    result_signal = Signal(dict)

    def __init__(self, manager: PackageManager, packages: list[str], parent: Any = None):
        super().__init__(parent)
        self.manager = manager
        self.packages = packages

    def run(self):
        async def fetch(pkg: str) -> tuple[str, dict[str, str]]:
            try:
                url, script = await self.manager.get_build_script(pkg)
                return pkg, {"url": url, "script": script}
            except Exception as e:
                return pkg, {"error": describe_error(e)}

        async def fetch_all():
            return await asyncio.gather(*(fetch(p) for p in self.packages))

        loop = asyncio.new_event_loop()
        try:
            self.result_signal.emit(dict(loop.run_until_complete(fetch_all())))
        finally:
            loop.close()


class BuildScriptDialog(QDialog):
    """One tab per package. accept() = go ahead; done(SKIP) = carry on without these packages."""

    SKIP = 2

    def __init__(self, manager: str, scripts: dict[str, dict[str, str]], action: str,
                 allow_skip: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Review {manager} build scripts")
        self.resize(760, 560)
        layout = QVBoxLayout(self)

        intro = QLabel(
            f"{manager} packages are built from user-submitted scripts that run as you. "
            "PolyGet installs them without further prompts, so read them now.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        failed = sorted(p for p, r in scripts.items() if "error" in r)
        self.tabs = QTabWidget()
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for pkg in sorted(scripts):
            result = scripts[pkg]
            page = QWidget()
            page_layout = QVBoxLayout(page)
            if "error" in result:
                msg = QLabel(f"Couldn't fetch the build script: {result['error']}")
                msg.setObjectName("review-error")
                msg.setWordWrap(True)
                page_layout.addWidget(msg)
                page_layout.addStretch()
            else:
                src = QLabel(result["url"])
                src.setObjectName("review-url")
                src.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                page_layout.addWidget(src)
                text = QPlainTextEdit(result["script"])
                text.setReadOnly(True)
                text.setFont(QFont(mono))
                text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                page_layout.addWidget(text)
            self.tabs.addTab(page, f"⚠ {pkg}" if "error" in result else pkg)
        layout.addWidget(self.tabs)

        if failed:
            warn = QLabel(f"Not reviewable: {', '.join(failed)}. PolyGet won't build a script you "
                          "haven't been able to read.")
            warn.setObjectName("review-error")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        buttons = QDialogButtonBox()
        self.btn_go = QPushButton(action)
        self.btn_go.setEnabled(not failed)
        buttons.addButton(self.btn_go, QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_skip = None
        if allow_skip:
            self.btn_skip = QPushButton(f"Skip {manager} packages")
            self.btn_skip.setObjectName("btn-scan")
            buttons.addButton(self.btn_skip, QDialogButtonBox.ButtonRole.ActionRole)
            self.btn_skip.clicked.connect(lambda: self.done(self.SKIP))
        cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel.setObjectName("btn-scan")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
