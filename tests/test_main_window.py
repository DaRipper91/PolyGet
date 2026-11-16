from pathlib import Path
from unittest.mock import patch

from app.ui.main_window import _parse_icon_from_file


def test_parse_icon_from_file_found(tmp_path: Path):
    """Valid .desktop file with Icon= line returns the icon name."""
    desktop = tmp_path / "app.desktop"
    desktop.write_text("[Desktop Entry]\nIcon=myapp\nExec=/usr/bin/myapp\n")
    assert _parse_icon_from_file(str(desktop)) == "myapp"


def test_parse_icon_from_file_not_found(tmp_path: Path):
    """Missing .desktop file: logs error and returns None."""
    missing = str(tmp_path / "nonexistent.desktop")
    logged = []
    with patch("app.ui.main_window._log", side_effect=lambda msg: logged.append(msg)):
        result = _parse_icon_from_file(missing)
    assert result is None
    assert any("desktop file not found" in msg for msg in logged)


def test_parse_icon_from_file_permission_error(tmp_path: Path):
    """PermissionError: logs error and returns None."""
    desktop = tmp_path / "app.desktop"
    desktop.write_text("[Desktop Entry]\nIcon=myapp\n")
    logged = []
    with patch("builtins.open", side_effect=PermissionError("denied")):
        with patch("app.ui.main_window._log", side_effect=lambda msg: logged.append(msg)):
            result = _parse_icon_from_file(str(desktop))
    assert result is None
    assert any("permission denied" in msg.lower() for msg in logged)


def test_parse_icon_from_file_os_error(tmp_path: Path):
    """OSError: logs error and returns None."""
    desktop = tmp_path / "app.desktop"
    desktop.write_text("[Desktop Entry]\nIcon=myapp\n")
    logged = []
    with patch("builtins.open", side_effect=OSError("i/o error")):
        with patch("app.ui.main_window._log", side_effect=lambda msg: logged.append(msg)):
            result = _parse_icon_from_file(str(desktop))
    assert result is None
    assert any("error reading desktop file" in msg for msg in logged)


def test_parse_icon_from_file_no_icon_line(tmp_path: Path):
    """.desktop file without Icon= line: returns None, no error logged."""
    desktop = tmp_path / "app.desktop"
    desktop.write_text("[Desktop Entry]\nExec=/usr/bin/myapp\n")
    logged = []
    with patch("app.ui.main_window._log", side_effect=lambda msg: logged.append(msg)):
        result = _parse_icon_from_file(str(desktop))
    assert result is None
    assert logged == []
