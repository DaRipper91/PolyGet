"""Centralized debug log stream for package-manager operations.

PolyGet components (ExecutionWorker, ScanWorker, repo syncs, etc.) emit
debug messages here. Two kinds of subscribers:

* CLI: ``run.py --debug <command>`` subscribes and prints to stderr so
  agents can watch all package-manager and repo-sync logs from the
  terminal.
* GUI: the Debug Console page subscribes and shows a live stream inside
  the application, alongside the existing Process Console.

Usage::

    from app.core.debug_log import debug_log
    debug_log.emit("dnf upgrade -y: Running as pid 1234")
    debug_log.emit("dnf upgrade -y: Upgraded: 1 package")

Callbacks are called synchronously from the emitting thread. GUI
subscribers should marshal to the main thread via Qt signals.
"""

from __future__ import annotations

from typing import Callable

try:  # Qt is optional — CLI-only use doesn't need it.
    from PySide6.QtCore import Signal, QObject

    class _DebugEmitter(QObject):
        """Qt signal carrier so GUI subscribers can connect across threads."""

        debug_log_signal = Signal(str)

    _emitter = _DebugEmitter()
    debug_log_signal = _emitter.debug_log_signal
    HAVE_QT = True
except Exception:  # PySide6 not installed or Qt can't initialize.
    HAVE_QT = False
    debug_log_signal = None  # type: ignore[assignment]

_callbacks: list[Callable[[str], None]] = []


class _DebugLog:
    """Namespace object so ``from app.core.debug_log import debug_log`` works."""

    def emit(self, message: str) -> None:
        emit(message)

    def subscribe(self, callback: Callable[[str], None]) -> None:
        subscribe(callback)

    def unsubscribe(self, callback: Callable[[str], None]) -> None:
        unsubscribe(callback)

    def enabled(self) -> bool:
        return enabled()


debug_log = _DebugLog()


def emit(message: str) -> None:
    """Publish *message* to every registered debug subscriber."""
    for cb in list(_callbacks):
        try:
            cb(message)
        except Exception:
            # A subscriber must never break the emitter.
            pass
    if HAVE_QT and debug_log_signal is not None:
        debug_log_signal.emit(message)


def subscribe(callback: Callable[[str], None]) -> None:
    """Register *callback* to receive debug messages."""
    _callbacks.append(callback)


def unsubscribe(callback: Callable[[str], None]) -> None:
    """Remove *callback* from the subscriber list."""
    try:
        _callbacks.remove(callback)
    except ValueError:
        pass


def enabled() -> bool:
    """True when at least one subscriber is listening."""
    return bool(_callbacks)
