import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.drivers.yarn import YarnManager
from app.core.manager import DriverError


def _check_updates(returncode, stdout=b"", stderr=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    with patch("app.core.drivers.yarn.run_capture", AsyncMock(return_value="/global\n")), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        return asyncio.run(YarnManager().check_updates())


@pytest.mark.parametrize("returncode", [1, 2])
def test_yarn_failed_scan_is_not_up_to_date(returncode):
    with pytest.raises(DriverError, match="network unavailable"):
        _check_updates(returncode, stderr=b"network unavailable")


def test_yarn_exit_1_with_table_reports_updates():
    out = b'{"type":"table","data":{"body":[["pkg","1","2","3"]]}}\n'
    assert _check_updates(1, out) == [{"name": "pkg", "current": "1", "new": "3"}]


def test_yarn_exit_0_with_no_updates_succeeds():
    assert _check_updates(0) == []


@pytest.mark.parametrize("stdout", [b"not json", b"[]", b'{"type":"table","data":{"body":[["pkg"]]}}'])
def test_yarn_malformed_scan_raises(stdout):
    with pytest.raises(DriverError):
        _check_updates(0, stdout)


@pytest.mark.parametrize("returncode", [0, 1])
def test_yarn_json_error_raises(returncode):
    with pytest.raises(DriverError, match="registry unavailable"):
        _check_updates(returncode, b'{"type":"error","data":"registry unavailable"}')


def test_yarn_error_on_stderr_does_not_allow_partial_updates():
    out = b'{"type":"table","data":{"body":[["pkg","1","2","3"]]}}\n'
    with pytest.raises(DriverError, match="registry unavailable"):
        _check_updates(1, out, b'{"type":"error","data":"registry unavailable"}')


def test_yarn_runs_outdated_in_global_directory(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    proc = MagicMock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b"", b""))
    with patch("app.core.drivers.yarn.run_capture", AsyncMock(return_value=str(tmp_path))), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as spawn:
        assert asyncio.run(YarnManager().check_updates()) == []
    assert spawn.call_args.args == ("yarn", "outdated", "--json")
    assert spawn.call_args.kwargs["cwd"] == tmp_path


def test_yarn_missing_global_manifest_means_nothing_installed(tmp_path):
    with patch("app.core.drivers.yarn.run_capture", AsyncMock(return_value=str(tmp_path))), \
         patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        assert asyncio.run(YarnManager().check_updates()) == []
    spawn.assert_not_called()


@pytest.mark.parametrize("directory", ["", "relative/path"])
def test_yarn_invalid_global_directory_raises(directory):
    with patch("app.core.drivers.yarn.run_capture", AsyncMock(return_value=directory)):
        with pytest.raises(DriverError, match="global directory"):
            asyncio.run(YarnManager().check_updates())


def test_yarn_global_directory_failure_raises():
    with patch("app.core.drivers.yarn.run_capture", AsyncMock(side_effect=DriverError("directory query failed"))):
        with pytest.raises(DriverError, match="directory query failed"):
            asyncio.run(YarnManager().check_updates())

def test_yarn_check_updates():
    manager = YarnManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{"type":"info","data":"some info"}\n'
            b'{"type":"table","data":{"body":[["typescript","5.0.0","5.0.4","5.1.0","global"],["webpack","5.70.0","5.75.0","5.80.0","global"]]}}\n',
            b""
        )
        with patch("app.core.drivers.yarn.run_capture", AsyncMock(return_value="/global")), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()
            
        assert len(updates) == 2
        assert updates[0] == {"name": "typescript", "current": "5.0.0", "new": "5.1.0"}
        assert updates[1] == {"name": "webpack", "current": "5.70.0", "new": "5.80.0"}

    asyncio.run(run_test())

def test_yarn_check_updates_timeout_raises_not_hangs():
    """A hung yarn outdated subprocess must raise, not hang forever (audit finding B1)."""
    manager = YarnManager()

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.communicate = MagicMock(return_value=asyncio.get_running_loop().create_future())
        with patch("app.core.drivers.yarn.run_capture", AsyncMock(return_value="/global")), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(RuntimeError):
                    await manager.check_updates()

    asyncio.run(run_test())


def test_yarn_list_installed_timeout_raises_not_hangs():
    """A hung yarn list subprocess must raise, not hang (audit finding B1), and must
    not report an empty install list as if the query had succeeded."""
    manager = YarnManager()

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.communicate = MagicMock(return_value=asyncio.get_running_loop().create_future())
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(DriverError):
                    await manager.list_installed()

    asyncio.run(run_test())


def test_yarn_list_installed():
    manager = YarnManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"info \"typescript@5.0.4\" has binaries\n"
            b"- typescript@5.0.4\n"
            b"- webpack@5.80.0\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["typescript", "webpack"]

    asyncio.run(run_test())
