"""The Package Managers page names this distro's own manager, never a hardcoded DNF."""

import pytest
from app.ui.main_window import managers_page_description


@pytest.mark.parametrize("manager", ["DNF", "Pacman", "APT"])
def test_names_this_distros_manager(manager):
    text = managers_page_description(manager)
    assert f"usually through {manager}." in text
    for other in {"DNF", "Pacman", "APT"} - {manager}:
        assert other not in text


def test_unknown_distro_names_no_manager():
    text = managers_page_description(None)
    assert "DNF" not in text
    assert "when PolyGet knows the install command for your distro" in text
