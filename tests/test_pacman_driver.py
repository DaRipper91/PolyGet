import asyncio
from unittest.mock import AsyncMock, patch
from app.core.drivers.pacman import PacmanManager

def test_pacman_check_updates_with_updates():
    manager = PacmanManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"linux 6.1.10 -> 6.1.11\n"
            b"systemd 252 -> 253 [ignored]\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()
            
        assert len(updates) == 2
        assert updates[0] == {"name": "linux", "current": "6.1.10", "new": "6.1.11"}
        assert updates[1] == {"name": "systemd", "current": "252", "new": "253"}

    asyncio.run(run_test())

def test_pacman_check_updates_no_updates():
    manager = PacmanManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        # Pacman -Qu returns 1 when there are no updates
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()
            
        assert updates == []

    asyncio.run(run_test())

def test_pacman_list_installed():
    manager = PacmanManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"bash\n"
            b"filesystem\n"
            b"linux\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["bash", "filesystem", "linux"]

    asyncio.run(run_test())

def test_pacman_search_packages():
    manager = PacmanManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"core/firefox 115.0-1\n"
            b"    Standalone web browser from Mozilla.\n"
            b"extra/gimp 2.10.34-2\n"
            b"    GNU Image Manipulation Program\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("firefox")
            
        assert len(results) == 2
        assert results[0] == {
            "name": "firefox",
            "id": "firefox",
            "description": "Standalone web browser from Mozilla.",
            "version": "115.0-1"
        }
        assert results[1]["name"] == "gimp"

    asyncio.run(run_test())


def test_pacman_check_updates_with_checkupdates_success():
    manager = PacmanManager()

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"bazaar 0.9.8-1.1 -> 0.9.9-1.1\n"
            b"deno 2.9.7-1.1 -> 2.9.7-2.1\n",
            b""
        )
        with patch("shutil.which", return_value="/usr/bin/checkupdates"), \
                patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            updates = await manager.check_updates()
            mock_exec.assert_called_once_with(
                "checkupdates",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

        assert len(updates) == 2
        assert updates[0] == {"name": "bazaar", "current": "0.9.8-1.1", "new": "0.9.9-1.1"}
        assert updates[1] == {"name": "deno", "current": "2.9.7-1.1", "new": "2.9.7-2.1"}

    asyncio.run(run_test())


def test_pacman_check_updates_with_checkupdates_none():
    manager = PacmanManager()

    async def run_test():
        mock_proc = AsyncMock()
        # checkupdates returns exit code 2 when there are no updates
        mock_proc.returncode = 2
        mock_proc.communicate.return_value = (b"", b"")
        with patch("shutil.which", return_value="/usr/bin/checkupdates"), \
                patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            updates = await manager.check_updates()
            mock_exec.assert_called_once_with(
                "checkupdates",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

        assert updates == []

    asyncio.run(run_test())


def test_pacman_check_updates_with_checkupdates_fallback():
    manager = PacmanManager()

    async def run_test():
        mock_checkupdates = AsyncMock()
        mock_checkupdates.returncode = 1
        mock_checkupdates.communicate.return_value = (b"", b"network error")

        mock_pacman = AsyncMock()
        mock_pacman.returncode = 0
        mock_pacman.communicate.return_value = (b"systemd 252 -> 253\n", b"")

        calls = [mock_checkupdates, mock_pacman]

        with patch("shutil.which", return_value="/usr/bin/checkupdates"), \
                patch("asyncio.create_subprocess_exec", side_effect=calls) as mock_exec:
            updates = await manager.check_updates()
            assert mock_exec.call_count == 2

        assert len(updates) == 1
        assert updates[0] == {"name": "systemd", "current": "252", "new": "253"}

    asyncio.run(run_test())
