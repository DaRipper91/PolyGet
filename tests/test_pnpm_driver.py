import asyncio
import errno
import os
import stat
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.pnpm import PnpmManager

def test_pnpm_check_updates():
    manager = PnpmManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{\n'
            b'  "typescript": {\n'
            b'    "current": "5.0.0",\n'
            b'    "latest": "5.1.0"\n'
            b'  }\n'
            b'}\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()
            
        assert len(updates) == 1
        assert updates[0] == {"name": "typescript", "current": "5.0.0", "new": "5.1.0"}

    asyncio.run(run_test())

def test_pnpm_check_updates_timeout_raises_not_hangs():
    """A hung pnpm outdated subprocess must raise, not hang forever (audit finding B1)."""
    manager = PnpmManager()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(RuntimeError):
                    await manager.check_updates()

    asyncio.run(run_test())


def test_pnpm_list_installed_timeout_returns_empty():
    """A hung pnpm list subprocess should fail open to [], not hang (audit finding B1)."""
    manager = PnpmManager()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await manager.list_installed()
                assert result == []

    asyncio.run(run_test())


def test_pnpm_list_installed():
    manager = PnpmManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'[\n'
            b'  {\n'
            b'    "dependencies": {\n'
            b'      "typescript": {},\n'
            b'      "eslint": {}\n'
            b'    }\n'
            b'  }\n'
            b']\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()

        assert installed == ["typescript", "eslint"]

    asyncio.run(run_test())


def _write_fake_pnpm(tmp_path, with_shebang):
    """Create a fake `pnpm` bin entry mimicking pnpm 11+'s install states.

    Without a shebang it reproduces the Asahi failure: direct execve answers
    ENOEXEC while shells retry it under `sh`.
    """
    fake = tmp_path / "pnpm"
    body = (
        '# placeholder without shebang — kernel answers ENOEXEC, shells retry under sh\n'
        'if [ "$1" = "outdated" ]; then\n'
        '  printf \'{"typescript": {"current": "5.0.0", "latest": "5.1.0"}}\'\n'
        'fi\n'
    )
    if with_shebang:
        body = "#!/bin/sh\n" + body
    fake.write_text(body)
    os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def test_pnpm_shebangless_shim_runs_via_sh(tmp_path, monkeypatch):
    """A shebang-less pnpm placeholder (Asahi: native binary never installed)
    must be routed through `sh` instead of failing with ENOEXEC."""
    fake = _write_fake_pnpm(tmp_path, with_shebang=False)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    async def run_test():
        # Premise: direct spawn of the placeholder answers ENOEXEC, exactly
        # like `asyncio.create_subprocess_exec("pnpm", ...)` did on Asahi.
        with pytest.raises(OSError) as exc:
            await asyncio.create_subprocess_exec(
                str(fake), "outdated",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        assert exc.value.errno == errno.ENOEXEC

        manager = PnpmManager()
        assert manager._pnpm_argv("outdated", "--global")[:2] == ["sh", str(fake)]
        updates = await manager.check_updates()
        assert updates == [{"name": "typescript", "current": "5.0.0", "new": "5.1.0"}]

    asyncio.run(run_test())


def test_pnpm_native_binary_runs_directly(tmp_path, monkeypatch):
    """A proper pnpm binary (shebang present) must keep the direct argv."""
    fake = _write_fake_pnpm(tmp_path, with_shebang=True)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    async def run_test():
        manager = PnpmManager()
        assert manager._pnpm_argv("outdated", "--global")[0] == "pnpm"
        updates = await manager.check_updates()
        assert updates == [{"name": "typescript", "current": "5.0.0", "new": "5.1.0"}]

    asyncio.run(run_test())


def test_pnpm_upgrade_command_uses_sh_fallback(tmp_path, monkeypatch):
    """Upgrade/install commands go through the same spawn path (tui.py uses
    create_subprocess_exec), so they need the `sh` hop too."""
    fake = _write_fake_pnpm(tmp_path, with_shebang=False)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    manager = PnpmManager()
    assert manager.get_upgrade_command() == ["sh", str(fake), "update", "--global"]
    assert manager.get_upgrade_command(["typescript"]) == ["sh", str(fake), "add", "--global", "typescript"]
    assert manager.get_install_command("eslint") == ["sh", str(fake), "add", "--global", "eslint"]
