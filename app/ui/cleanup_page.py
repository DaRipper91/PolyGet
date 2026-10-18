"""The Clean up page: reclaimable space each manager reports (orphans, caches, leftover data)."""

import asyncio
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.core.janitor import human_size
from app.ui.themes import themed
from app.core.manager import PackageManager, describe_error

_TARGET_ROLE = Qt.ItemDataRole.UserRole
_ITEMS_SHOWN = 50


def is_destructive(target: dict[str, Any]) -> bool:
    """Deletes user data or uninstalls packages rather than clearing caches."""
    return target.get("id") in ("leftover-data", "orphans") or target.get("command", [])[:1] == ["rm"]


class CleanupScanWorker(QThread):
    """get_cleanup_targets() across managers. {name: {"ok", "result"} | {"error"} | {"unsupported"}}."""

    result_signal = Signal(dict)

    def __init__(self, managers: list[PackageManager], parent: Any = None):
        super().__init__(parent)
        self.managers = managers

    def run(self):
        async def one(mgr: PackageManager):
            try:
                return mgr.name, {"ok": True, "result": await mgr.get_cleanup_targets()}
            except NotImplementedError:
                return mgr.name, {"ok": False, "unsupported": True}
            except Exception as e:  # a failed query is a failure, never "nothing to clean"
                return mgr.name, {"ok": False, "error": describe_error(e)}

        async def everything():
            return dict(await asyncio.gather(*(one(m) for m in self.managers)))

        loop = asyncio.new_event_loop()
        try:
            self.result_signal.emit(loop.run_until_complete(everything()))
        finally:
            loop.close()


class CleanupPage(QWidget):
    scan_requested = Signal()
    clean_requested = Signal(list)  # the ticked target dicts

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header = QHBoxLayout()
        self.summary = QLabel("Find orphaned packages, caches and leftover app data.")
        self.summary.setObjectName("summary-label")
        self.summary.setWordWrap(True)
        header.addWidget(self.summary, 1)
        self.btn_scan = QPushButton("Scan")
        self.btn_scan.setObjectName("btn-scan")
        self.btn_scan.clicked.connect(self.scan_requested.emit)
        header.addWidget(self.btn_scan)
        self.btn_clean = QPushButton("Clean selected")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(lambda: self.clean_requested.emit(self.selected_targets()))
        header.addWidget(self.btn_clean)
        layout.addLayout(header)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["What", "Manager", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(lambda *_: self._refresh_buttons())
        layout.addWidget(self.tree)

        note = QLabel("Ticked items are cleaned with each manager's own command. Orphan packages and "
                      "leftover app data are never ticked for you: removing them cannot be undone.")
        note.setWordWrap(True)
        note.setObjectName("group-footer")
        layout.addWidget(note)

    def set_scanning(self) -> None:
        self.tree.clear()
        self.summary.setText("Scanning…")
        self.btn_scan.setEnabled(False)
        self.btn_clean.setEnabled(False)

    def set_results(self, results: dict[str, dict]) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        known, count, failures = 0, 0, 0
        for name in sorted(results, key=str.lower):
            res = results[name]
            if res.get("unsupported"):
                continue
            if not res.get("ok"):
                failures += 1
                row = QTreeWidgetItem([f"Couldn't check: {res.get('error', 'unknown error')}", name, ""])
                row.setForeground(0, QBrush(QColor(themed("#f38ba8"))))
                row.setData(0, _TARGET_ROLE, None)
                row.setToolTip(0, res.get("error", ""))
                self.tree.addTopLevelItem(row)
                continue
            for t in res["result"]:
                count += 1
                known += t["bytes"] or 0
                label = t["label"] + (f" ({len(t['items'])})" if t["items"] else "")
                row = QTreeWidgetItem([label, t["manager"], human_size(t["bytes"])])
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(0, Qt.CheckState.Unchecked if is_destructive(t) else Qt.CheckState.Checked)
                row.setData(0, _TARGET_ROLE, t)
                row.setToolTip(0, (t["detail"] + "\n\n" if t["detail"] else "") + " ".join(t["command"]))
                for item in t["items"][:_ITEMS_SHOWN]:
                    row.addChild(QTreeWidgetItem([item, "", ""]))
                if len(t["items"]) > _ITEMS_SHOWN:
                    row.addChild(QTreeWidgetItem([f"…and {len(t['items']) - _ITEMS_SHOWN} more", "", ""]))
                self.tree.addTopLevelItem(row)
        self.tree.blockSignals(False)
        if count:
            text = f"{count} thing{'s' if count != 1 else ''} to clean, at least {human_size(known)} reclaimable"
        else:
            text = "Nothing to clean."
        if failures:
            text += f" · {failures} manager{'s' if failures != 1 else ''} couldn't be checked"
        self.summary.setText(text)
        self.btn_scan.setEnabled(True)
        self._refresh_buttons()

    def selected_targets(self) -> list[dict[str, Any]]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            row = self.tree.topLevelItem(i)
            t = row.data(0, _TARGET_ROLE)
            if t and row.checkState(0) == Qt.CheckState.Checked:
                out.append(t)
        return out

    def _refresh_buttons(self) -> None:
        n = len(self.selected_targets())
        self.btn_clean.setEnabled(n > 0)
        self.btn_clean.setText(f"Clean {n} selected" if n else "Clean selected")
