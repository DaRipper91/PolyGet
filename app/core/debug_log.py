"""Centralized debug log stream for package-manager operations.

PolyGet components (ExecutionWorker, ScanWorker, repo syncs, etc.) emit
debug messages here. Multiple kinds of subscribers:

* CLI: ``run.py --debug <command>`` subscribes and prints to stderr so
  agents can watch all package-manager and repo-sync logs from the
  terminal.
* GUI: the Debug Console page subscribes and shows a live stream inside
  the application, alongside the existing Process Console.
* File: when enabled (``POLYGET_DEBUG_FILE`` env var or ``--debug-file``
  flag), every message is appended to a JSONL file at a known path so
  AI coding assistants (Claude Code, Codex, Copilot, OpenCode, etc.) can
  read or ``tail -f`` the structured log without running PolyGet themselves.
* State dump: ``dump_state()`` writes a JSON snapshot of the current
  manager/update/scan-error state to a known file.

Usage::

    from app.core.debug_log import debug_log
    debug_log.emit("dnf upgrade -y: Running as pid 1234")
    debug_log.emit("dnf upgrade -y: Upgraded: 1 package")

    # AI tools read ~/.config/polyget/debug.log (JSONL) or call:
    #   polyget debug --tail 50
    #   polyget debug --state

Callbacks are called synchronously from the emitting thread. GUI
subscribers should marshal to the main thread via Qt signals.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

_DEBUG_LOG_PATH = Path.home() / ".config" / "polyget" / "debug.log"
_STATE_DUMP_PATH = Path.home() / ".config" / "polyget" / "state.json"
_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB rotation threshold

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
_file_logging_enabled: bool = False
_file_handle = None


def _enable_file_logging(path: Path | None = None) -> None:
    """Enable appending debug messages to a JSONL file."""
    global _file_logging_enabled, _file_handle, _DEBUG_LOG_PATH
    if path is not None:
        _DEBUG_LOG_PATH = path
    _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Rotate if too large
    if _DEBUG_LOG_PATH.exists() and _DEBUG_LOG_PATH.stat().st_size > _MAX_LOG_BYTES:
        rotated = _DEBUG_LOG_PATH.with_suffix(".log.1")
        _DEBUG_LOG_PATH.rename(rotated)
    _file_handle = open(_DEBUG_LOG_PATH, "a", encoding="utf-8")
    _file_logging_enabled = True


def _disable_file_logging() -> None:
    """Close and disable file logging."""
    global _file_logging_enabled, _file_handle
    if _file_handle is not None:
        _file_handle.close()
        _file_handle = None
    _file_logging_enabled = False


def _write_to_file(message: str) -> None:
    """Write a single debug message to the JSONL log file."""
    if not _file_logging_enabled or _file_handle is None:
        return
    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "msg": message,
    }
    try:
        _file_handle.write(json.dumps(entry) + "\n")
        _file_handle.flush()
    except Exception:
        pass


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

    def file_logging_enabled(self) -> bool:
        return _file_logging_enabled

    def enable_file_logging(self, path: Path | None = None) -> None:
        _enable_file_logging(path)

    def disable_file_logging(self) -> None:
        _disable_file_logging()

    def dump_state(self, state: dict[str, Any] | None = None) -> None:
        """Write a JSON snapshot of PolyGet's current state for AI tools."""
        _STATE_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        if state is None:
            state = {}
        state["_ts"] = time.time()
        state["_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        try:
            _STATE_DUMP_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    @property
    def log_path(self) -> Path:
        return _DEBUG_LOG_PATH

    @property
    def state_path(self) -> Path:
        return _STATE_DUMP_PATH


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
    _write_to_file(message)


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
    return bool(_callbacks) or _file_logging_enabled


# Auto-enable file logging if POLYGET_DEBUG_FILE env var is set
if os.environ.get("POLYGET_DEBUG_FILE"):
    _enable_file_logging(Path(os.environ["POLYGET_DEBUG_FILE"]))