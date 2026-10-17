import asyncio

import pytest

from app.core.drivers.apt import AptManager
from app.core.drivers.dnf import DnfManager
from app.core.drivers.npm import NpmManager
from app.core.drivers.pacman import PacmanManager
from app.core.manager import DriverError


def run(coro):
    return asyncio.run(coro)


def test_dnf_preview_lists_installed_dependents(scripted_exec):
    scripted_exec.add("dnf repoquery --installed --whatrequires gtk3", "gimp\n\nevince\ngimp\n")
    assert run(DnfManager().preview_remove("gtk3")) == {
        "remove": ["gtk3", "evince", "gimp"], "blocked_by": []}
    argv = scripted_exec.calls[0][0]
    assert argv[0] == "dnf" and "pkexec" not in argv  # read-only, no root


def test_dnf_preview_failure_raises_instead_of_claiming_no_dependents(scripted_exec):
    scripted_exec.add("dnf repoquery", rc=1, stderr="Error: cache broken")
    with pytest.raises(DriverError):
        run(DnfManager().preview_remove("gtk3"))


def test_pacman_preview_lists_targets(scripted_exec):
    scripted_exec.add("pacman -Rsp --print-format %n gimp", "gimp\nbabl\ngegl\n")
    assert run(PacmanManager().preview_remove("gimp")) == {
        "remove": ["gimp", "babl", "gegl"], "blocked_by": []}


def test_pacman_preview_reports_what_blocks_the_removal(scripted_exec):
    scripted_exec.add(
        "pacman -Rsp", rc=1,
        stderr="error: failed to prepare transaction (could not satisfy dependencies)\n"
               ":: removing gtk3 breaks dependency 'gtk3' required by gimp\n"
               ":: removing gtk3 breaks dependency 'gtk3>=3.24' required by evince\n")
    assert run(PacmanManager().preview_remove("gtk3")) == {
        "remove": ["gtk3"], "blocked_by": ["evince", "gimp"]}


def test_pacman_preview_unknown_failure_raises(scripted_exec):
    scripted_exec.add("pacman -Rsp", rc=1, stderr="error: target not found: nope\n")
    with pytest.raises(DriverError):
        run(PacmanManager().preview_remove("nope"))


def test_apt_preview_parses_simulated_removals(scripted_exec):
    scripted_exec.add("apt-get -s remove gimp",
                      "Reading package lists...\nRemv gimp [2.10.36-3]\nRemv gimp-plugin-registry [9]\n")
    assert run(AptManager().preview_remove("gimp")) == {
        "remove": ["gimp", "gimp-plugin-registry"], "blocked_by": []}


def test_managers_without_dependencies_remove_just_the_package():
    assert run(NpmManager().preview_remove("typescript")) == {"remove": ["typescript"], "blocked_by": []}
    assert NpmManager().get_remove_command("typescript") == ["npm", "uninstall", "-g", "typescript"]
