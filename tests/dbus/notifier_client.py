"""Drives app.ui.notifier.Notifier against the fake server (see test_notifier.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

app = QCoreApplication(sys.argv)
from app.ui.notifier import Notifier  # noqa: E402

n = Notifier(lambda: None, signal_service="")  # the fake's clicks don't come from the name owner
print("AVAILABLE", n.service_available(), flush=True)
n.action_invoked.connect(lambda key, action: print("ACTION", key, action, flush=True))
QTimer.singleShot(100, lambda: n.notify("updates", "6 updates ready", "DNF 3 · it's\nmajor",
                                        [("update-all", "Update all"), ("open", "Open")]))
QTimer.singleShot(1200, lambda: n.notify("updates", "7 updates ready", "replaced", [], progress=40))
QTimer.singleShot(2000, lambda: n.close("updates"))
QTimer.singleShot(2600, app.quit)
app.exec()
