"""Desktop notifications with buttons, through the freedesktop notification service.

Qt's QSystemTrayIcon.showMessage() can't carry buttons and needs the tray icon. This talks to
org.freedesktop.Notifications (Plasma, GNOME, and most other desktops) instead:

- Sending goes through `gdbus` (part of GLib, on every Fedora/Arch desktop), because the
  Notify call needs exact D-Bus types (uint32 id, byte urgency, a{sv} hints) that PySide6
  can't express. Arguments are passed as an argv list and written as GVariant literals, never
  through a shell.
- Clicks come back as the service's ActionInvoked signal, received with QtDBus.

Each notification has a `key` ("updates", "upgrade", ...): sending the same key again replaces
the earlier notification in place instead of stacking a new one. Without the service (or
gdbus) notifications fall back to the tray icon's plain message, without buttons.
"""

from __future__ import annotations

import re
import shutil
from typing import Callable

from PySide6.QtCore import QObject, QProcess, Signal, Slot, SLOT
from PySide6.QtDBus import QDBusConnection

SERVICE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
IFACE = "org.freedesktop.Notifications"

LOW, NORMAL, CRITICAL = 0, 1, 2  # freedesktop urgency levels


def gv_str(text: str) -> str:
    """A GVariant text-format string literal (gdbus parses every argument as GVariant)."""
    escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return f"'{escaped}'"


def notify_argv(replaces_id: int, title: str, body: str, actions: list[tuple[str, str]],
                urgency: int, progress: int | None, gdbus: str = "gdbus") -> list[str]:
    """The gdbus command for one Notify call (exposed for tests)."""
    flat = [part for key, label in actions for part in (key, label)]
    hints = [f"'urgency': <byte {urgency}>", "'desktop-entry': <'polyget'>"]
    if progress is not None:
        hints.append(f"'value': <int32 {max(0, min(100, progress))}>")  # Plasma's progress bar
    return [
        gdbus, "call", "--session", "--dest", SERVICE, "--object-path", PATH,
        "--method", f"{IFACE}.Notify",
        gv_str("PolyGet"), f"uint32 {replaces_id}", gv_str("polyget"), gv_str(title), gv_str(body),
        "[" + ", ".join(gv_str(p) for p in flat) + "]" if flat else "@as []",
        "{" + ", ".join(hints) + "}",
        "int32 -1",
    ]


_ID = re.compile(r"\(uint32 (\d+),\)")


class Notifier(QObject):
    """Sends notifications and reports button clicks as action_invoked(key, action)."""

    action_invoked = Signal(str, str)  # notification key, action key ("default" = body clicked)

    def __init__(self, tray_getter: Callable[[], object | None], parent: QObject | None = None,
                 signal_service: str = SERVICE):
        super().__init__(parent)
        self._tray_getter = tray_getter
        self._ids: dict[str, int] = {}          # key -> server id, for replace-in-place
        self._procs: list[QProcess] = []
        self._gdbus = shutil.which("gdbus")
        bus = QDBusConnection.sessionBus()
        self._bus_ok = bus.isConnected()
        if self._bus_ok:
            # signal_service is "" only in tests, where the fake sender doesn't own the name.
            bus.connect(signal_service, PATH, IFACE, "ActionInvoked", self,
                        SLOT("_on_action_invoked(uint,QString)"))
            bus.connect(signal_service, PATH, IFACE, "NotificationClosed", self,
                        SLOT("_on_closed(uint,uint)"))

    def service_available(self) -> bool:
        if not (self._bus_ok and self._gdbus):
            return False
        reply = QDBusConnection.sessionBus().interface().isServiceRegistered(SERVICE)
        return bool(reply.value()) if reply.isValid() else False

    def notify(self, key: str, title: str, body: str = "", actions: list[tuple[str, str]] = (),
               urgency: int = NORMAL, progress: int | None = None) -> bool:
        """Show (or replace) the `key` notification. Returns False if only the tray fallback
        (or nothing) could show it."""
        if self.service_available():
            argv = notify_argv(self._ids.get(key, 0), title, body, list(actions), urgency, progress,
                               self._gdbus)
            proc = QProcess(self)
            proc.finished.connect(lambda *_a, p=proc, k=key: self._on_sent(p, k))
            self._procs.append(proc)
            proc.start(argv[0], argv[1:])
            return True
        tray = self._tray_getter()
        if tray is not None:
            from PySide6.QtWidgets import QSystemTrayIcon
            icon = (QSystemTrayIcon.MessageIcon.Critical if urgency == CRITICAL
                    else QSystemTrayIcon.MessageIcon.Information)
            tray.showMessage(title, body, icon)
        return False

    def close(self, key: str) -> None:
        nid = self._ids.pop(key, None)
        if nid is None or not self.service_available():
            return
        proc = QProcess(self)
        proc.finished.connect(lambda *_a, p=proc: self._procs.remove(p) if p in self._procs else None)
        self._procs.append(proc)
        proc.start(self._gdbus, ["call", "--session", "--dest", SERVICE, "--object-path", PATH,
                                 "--method", f"{IFACE}.CloseNotification", f"uint32 {nid}"])

    def _on_sent(self, proc: QProcess, key: str) -> None:
        out = bytes(proc.readAllStandardOutput()).decode(errors="ignore")
        match = _ID.search(out)
        if match:
            self._ids[key] = int(match.group(1))
        if proc in self._procs:
            self._procs.remove(proc)

    @Slot("uint", "QString")
    def _on_action_invoked(self, nid: int, action: str) -> None:
        key = next((k for k, v in self._ids.items() if v == nid), None)
        if key is not None:
            self.action_invoked.emit(key, action)

    @Slot("uint", "uint")
    def _on_closed(self, nid: int, _reason: int) -> None:
        for key, value in list(self._ids.items()):
            if value == nid:
                del self._ids[key]
