import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.drivers.yarn import YarnManager
from app.core.manager import DriverError

def _proc(returncode, stdout=b"", stderr=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _check_updates(tmp_path, outdated_proc, with_manifest=True):
    """Run check_updates with `yarn global dir` pointing at tmp_path; return (result, argv/cwd calls)."""
    if with_manifest:
        (tmp_path / "package.json").write_text("{}")
    calls = []

    async def fake_exec(*argv, cwd=None, **kw):
        calls.append((list(argv), cwd))
        if list(argv) == ["yarn", "global", "dir"]:
            return _proc(0, str(tmp_path).encode() + b"\n")
        return outdated_proc

    with patch("asyncio.create_subprocess_exec", fake_exec):
        return asyncio.run(YarnManager().check_updates()), calls


# Outputs below were captured from real Yarn 1.22.22 runs.
TABLE = (
    b'{"type":"warning","data":"package.json: No license field"}\n'
    b'{"type":"table","data":{"head":["Package","Current","Wanted","Latest","Package Type","URL"],'
    b'"body":[["is-odd","2.0.0","2.0.0","3.0.1","dependencies","https://github.com/jonschlinkert/is-odd"]]}}\n'
)


def test_yarn_check_updates_runs_outdated_in_the_global_dir(tmp_path):
    updates, calls = _check_updates(tmp_path, _proc(1, TABLE))
    assert updates == [{"name": "is-odd", "current": "2.0.0", "new": "3.0.1"}]
    # `yarn global outdated` is not a Yarn Classic subcommand; it must never be used.
    assert calls[-1] == (["yarn", "outdated", "--json"], tmp_path)


def test_yarn_up_to_date_exit_0(tmp_path):
    updates, _ = _check_updates(tmp_path, _proc(0, b'{"type":"warning","data":"package.json: No license field"}\n'))
    assert updates == []


def test_yarn_no_global_manifest_means_nothing_installed(tmp_path):
    updates, calls = _check_updates(tmp_path, _proc(1, b""), with_manifest=False)
    assert updates == []
    assert len(calls) == 1  # never ran `yarn outdated`


def test_yarn_error_line_is_a_failed_scan_not_up_to_date(tmp_path):
    out = b'{"type":"error","data":"No lockfile in this directory. Run `yarn install` to generate one."}\n'
    with pytest.raises(DriverError, match="No lockfile"):
        _check_updates(tmp_path, _proc(1, out))


def test_yarn_exit_1_with_no_output_raises(tmp_path):
    with pytest.raises(DriverError, match="status 1"):
        _check_updates(tmp_path, _proc(1, b"", b"boom"))


def test_yarn_global_dir_failure_raises(tmp_path):
    async def fake_exec(*argv, **kw):
        return _proc(1, b"", b"yarn: command broke")

    with patch("asyncio.create_subprocess_exec", fake_exec):
        with pytest.raises(DriverError):
            asyncio.run(YarnManager().check_updates())


def test_yarn_check_updates_timeout_raises_not_hangs():
    """A hung yarn outdated subprocess must raise, not hang forever (audit finding B1)."""
    manager = YarnManager()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
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
