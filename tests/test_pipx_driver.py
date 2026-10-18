import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app.core.drivers.pipx import PipxManager


def test_pipx_driver_imports():
    """Validate that the PipxManager driver can be imported and instantiated."""
    manager = PipxManager()
    assert manager.name == "Pipx"
    assert manager.category == "Language/Dev"


def test_pipx_driver_availability_true():
    """Test availability when pipx binary is in PATH."""
    with patch("shutil.which", return_value="/usr/bin/pipx"):
        manager = PipxManager()
        assert manager.is_available() is True


def test_pipx_driver_availability_false():
    """Test availability when pipx binary is NOT in PATH."""
    with patch("shutil.which", return_value=None):
        manager = PipxManager()
        assert manager.is_available() is False


def test_pipx_get_upgrade_command():
    """Test upgrade command generation."""
    manager = PipxManager()
    assert manager.get_upgrade_command() == ["pipx", "upgrade-all"]
    assert manager.get_upgrade_command(["pkg1", "pkg2"]) == ["pipx", "upgrade", "pkg1", "pkg2"]


def test_pipx_check_updates():
    """Test check_updates parses packages and gathers updates in parallel."""
    async def run_test():
        manager = PipxManager()

        mock_pipx_list_proc = AsyncMock()
        mock_pipx_list_proc.returncode = 0
        mock_pipx_list_proc.communicate.return_value = (b"package1 1.0.0\npackage2 2.0.0\n", b"")

        mock_pip_proc1 = AsyncMock()
        mock_pip_proc1.returncode = 0
        mock_pip_proc1.communicate.return_value = (
            b'[{"name": "package1", "version": "1.0.0", "latest_version": "1.1.0"}]',
            b""
        )

        mock_pip_proc2 = AsyncMock()
        mock_pip_proc2.returncode = 0
        mock_pip_proc2.communicate.return_value = (
            b'[{"name": "package2", "version": "2.0.0", "latest_version": "2.2.0"}]',
            b""
        )

        def create_subprocess_exec_side_effect(*args, **kwargs):
            if args[0] == "pipx" and args[1] == "list":
                return mock_pipx_list_proc
            elif args[:2] == ("pipx", "runpip") and args[2] == "package1":
                return mock_pip_proc1
            elif args[:2] == ("pipx", "runpip") and args[2] == "package2":
                return mock_pip_proc2
            raise ValueError(f"Unexpected subprocess call: {args}")

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec_side_effect):
            updates = await manager.check_updates()

        assert len(updates) == 2
        assert updates[0] == {"name": "package1", "current": "1.0.0", "new": "1.1.0"}
        assert updates[1] == {"name": "package2", "current": "2.0.0", "new": "2.2.0"}

    asyncio.run(run_test())


def test_pipx_check_updates_surfaces_per_package_failure_not_false_negative():
    """A broken/corrupted per-package pip check must raise, not be silently reported as
    'up to date' (audit finding B2 — this is the actual CLAUDE.md 'fake PyPI lookup' bug)."""
    async def run_test():
        manager = PipxManager()

        mock_pipx_list_proc = AsyncMock()
        mock_pipx_list_proc.communicate.return_value = (b"package1 1.0.0\n", b"")

        mock_pip_proc1 = AsyncMock()
        mock_pip_proc1.returncode = 0
        # Malformed JSON simulates a corrupted venv / broken pip output.
        mock_pip_proc1.communicate.return_value = (b"not valid json{{{", b"")

        def create_subprocess_exec_side_effect(*args, **kwargs):
            if args[0] == "pipx" and args[1] == "list":
                return mock_pipx_list_proc
            return mock_pip_proc1

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec_side_effect):
            with pytest.raises(RuntimeError):
                await manager.check_updates()

    asyncio.run(run_test())


# --- the check goes through `pipx runpip`, not a venv's own bin/pip (which current pipx venvs do not have) ---

RUFF_OUTDATED = '[{"name":"ruff","version":"0.16.9","latest_version":"0.17.1","latest_filetype":"wheel"}]'


def test_pipx_checks_a_venv_that_has_no_bin_pip(scripted_exec):
    """Regression: with no venvs/<name>/bin/pip the old code returned [] ("nothing checkable"), so apps that
    pipx itself listed as outdated were reported as up to date."""
    scripted_exec.add("pipx runpip ruff list", stdout=RUFF_OUTDATED)
    with patch("os.path.exists", return_value=False):
        result = asyncio.run(PipxManager()._check_package("ruff"))
    assert result == [{"name": "ruff", "current": "0.16.9", "new": "0.17.1"}]


def test_pipx_uses_the_pip_flag_that_exists(scripted_exec):
    scripted_exec.add("pipx runpip", stdout="[]")
    asyncio.run(PipxManager()._check_package("ruff"))
    argv = scripted_exec.calls[0][0]
    assert argv == ["pipx", "runpip", "ruff", "list", "--outdated", "--format=json"]
    assert "--json" not in argv  # pip and uv both reject it


def test_pipx_up_to_date_package_is_an_empty_result(scripted_exec):
    scripted_exec.add("pipx runpip tivars", stdout="[]")
    assert asyncio.run(PipxManager()._check_package("tivars")) == []
    scripted_exec.rules.clear()
    scripted_exec.add("pipx runpip tivars", stdout="")
    assert asyncio.run(PipxManager()._check_package("tivars")) == []


def test_pipx_runpip_failure_is_an_error_not_a_clean_result(scripted_exec):
    scripted_exec.add("pipx runpip ruff", rc=1, stderr="error: failed to query the index\nno route to host")
    with pytest.raises(RuntimeError, match=r"exited with status 1: no route to host"):
        asyncio.run(PipxManager()._check_package("ruff"))


def test_pipx_runpip_missing_pipx_is_an_error(scripted_exec):
    with pytest.raises(RuntimeError, match="update check failed for 'ruff'"):
        asyncio.run(PipxManager()._check_package("ruff"))  # nothing scripted: FileNotFoundError


def test_pipx_runpip_timeout_is_an_error():
    async def run_test():
        proc = AsyncMock()
        proc.communicate.side_effect = asyncio.TimeoutError()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(RuntimeError, match="update check failed for 'ruff'"):
                await PipxManager()._check_package("ruff")

    asyncio.run(run_test())


# --- an app installed from a local path or VCS must not be compared with an unrelated same-named PyPI project ---

from app.core.drivers.pipx import _is_local_source

PIPX_JSON = (
    '{"venvs": {'
    '"six": {"metadata": {"main_package": {"package": "six", "package_or_url": "/home/u/proj/six"}}},'
    '"pycowsay": {"metadata": {"main_package": {"package": "pycowsay", "package_or_url": "pycowsay"}}}}}'
)


@pytest.mark.parametrize("spec,expected", [
    ("ruff", False), ("ruff==0.16.9", False), ("ruff[extra]>=1", False),
    ("/home/u/proj", True), ("./proj", True), ("git+https://example.com/x.git", True), ("https://example.com/x.whl", True),
    ("pkg @ https://example.com/x", True), ("file:///a/b", True), ("dist/pkg-1.0.tar.gz", True), ("pkg-1.0-py3-none-any.whl", True),
])
def test_local_source_classification(spec, expected):
    assert _is_local_source(spec) is expected


def test_pipx_local_path_app_is_never_looked_up_against_pypi(scripted_exec):
    scripted_exec.add("pipx list --short", stdout="pycowsay 0.0.0.1\nsix 0.0.1\n")
    scripted_exec.add("pipx list --json", stdout=PIPX_JSON)
    scripted_exec.add("pipx runpip pycowsay", stdout='[{"name":"pycowsay","version":"0.0.0.1","latest_version":"0.0.0.2"}]')
    scripted_exec.add("pipx runpip six", stdout='[{"name":"six","version":"0.0.1","latest_version":"1.17.0"}]')  # must not be consulted
    updates = asyncio.run(PipxManager().check_updates())
    assert updates == [{"name": "pycowsay", "current": "0.0.0.1", "new": "0.0.0.2"}]
    assert not any("runpip" in c[0] and "six" in c[0] for c in scripted_exec.calls)


@pytest.mark.parametrize("json_stdout,rc", [("not json", 0), ("", 1), ('{"venvs": null}', 0)], ids=["malformed", "command-failed", "no-venvs"])
def test_pipx_unreadable_source_metadata_keeps_the_index_check_instead_of_hiding_apps(scripted_exec, json_stdout, rc):
    scripted_exec.add("pipx list --short", stdout="six 0.0.1\n")
    scripted_exec.add("pipx list --json", stdout=json_stdout, rc=rc)
    scripted_exec.add("pipx runpip six", stdout='[{"name":"six","version":"0.0.1","latest_version":"1.17.0"}]')
    assert [u["name"] for u in asyncio.run(PipxManager().check_updates())] == ["six"]


def test_pipx_every_app_local_means_no_updates_and_no_index_lookups(scripted_exec):
    scripted_exec.add("pipx list --short", stdout="six 0.0.1\n")
    scripted_exec.add("pipx list --json", stdout=PIPX_JSON)
    assert asyncio.run(PipxManager().check_updates()) == []
    assert not any("runpip" in " ".join(c[0]) for c in scripted_exec.calls)
