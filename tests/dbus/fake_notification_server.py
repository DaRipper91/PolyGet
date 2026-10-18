"""A stand-in org.freedesktop.Notifications for tests, run on a private session bus.

Prints every call it receives, and "clicks" the first action of each notification by
emitting ActionInvoked (via gdbus, which can type the id as uint32 like a real server).
"""
import sys
from PySide6.QtCore import QCoreApplication, QObject, Slot, ClassInfo, QTimer
from PySide6.QtDBus import QDBusConnection, QDBusMessage

@ClassInfo({"D-Bus Interface": "org.freedesktop.Notifications"})
class Server(QObject):
    def __init__(self):
        super().__init__()
        self.next_id = 41
    @Slot(str, "uint", str, str, str, "QStringList", "QVariantMap", int, result="uint")
    def Notify(self, app, replaces, icon, summary, body, actions, hints, timeout):
        nid = replaces or self.next_id
        self.next_id += 1
        print("NOTIFY", nid, replaces, summary, "|", body.replace("\n", "\\n"), actions, dict(hints), flush=True)
        if actions:
            QTimer.singleShot(200, lambda: self.click(nid, actions[0]))
        return nid
    @Slot("uint")
    def CloseNotification(self, nid):
        print("CLOSE", nid, flush=True)
    def click(self, nid, key):
        import subprocess
        r = subprocess.run(["gdbus", "emit", "--session", "--object-path", "/org/freedesktop/Notifications",
                            "--signal", "org.freedesktop.Notifications.ActionInvoked", f"uint32 {nid}", f"'{key}'"])
        print("CLICK", nid, key, r.returncode, flush=True)

app = QCoreApplication(sys.argv)
bus = QDBusConnection.sessionBus()
s = Server()
print("REGISTER", bus.registerService("org.freedesktop.Notifications"),
      bus.registerObject("/org/freedesktop/Notifications", s, QDBusConnection.RegisterOption.ExportAllSlots), flush=True)
QTimer.singleShot(int(sys.argv[1]) if len(sys.argv) > 1 else 4000, app.quit)
app.exec()
