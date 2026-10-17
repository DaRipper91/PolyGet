import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app.core.drivers.dnf import DnfManager
from app.core.manager import DriverError


def test_dnf_driver_imports():
    """Validate that the DnfManager driver can be imported and instantiated."""
    manager = DnfManager()
    assert manager.name == "DNF"
    assert manager.category == "System"


def test_dnf_driver_availability_true():
    """Test availability when dnf binary is in PATH."""
    with patch("shutil.which", return_value="/usr/bin/dnf"):
        manager = DnfManager()
        assert manager.is_available() is True


def test_dnf_driver_availability_false():
    """Test availability when dnf binary is NOT in PATH."""
    with patch("shutil.which", return_value=None):
        manager = DnfManager()
        assert manager.is_available() is False


def test_dnf_get_upgrade_command():
    """Test upgrade command generation uses pkexec."""
    manager = DnfManager()
    assert manager.get_upgrade_command() == ["pkexec", "dnf", "upgrade", "-y"]
    assert manager.get_upgrade_command(["pkg1"]) == ["pkexec", "dnf", "upgrade", "-y", "pkg1"]


def test_dnf_get_sync_command():
    """Test sync command generation uses pkexec."""
    manager = DnfManager()
    assert manager.get_sync_command() == ["pkexec", "dnf", "makecache"]


def test_dnf_check_updates_json():
    """Test check_updates parses packages using dnf check-update --json."""
    async def run_test():
        manager = DnfManager()

        mock_json_proc = AsyncMock()
        mock_json_proc.returncode = 100
        mock_json_proc.communicate.return_value = (
            b'{"upgrades": [{"name": "package1", "evr": "1.1.0"}]}',
            b""
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_json_proc) as mock_exec:
            updates = await manager._query_updates()
            mock_exec.assert_called_once_with(
                "dnf", "check-update", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

        assert len(updates) == 1
        assert updates[0] == {"name": "package1", "current": "Installed", "new": "1.1.0"}

    asyncio.run(run_test())


def test_dnf_check_updates_timeout_raises_not_hangs():
    """A hung dnf check-update subprocess must raise, not hang forever (audit finding B1)."""
    async def run_test():
        manager = DnfManager()

        mock_proc = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(RuntimeError):
                    await manager.check_updates()

    asyncio.run(run_test())


def test_dnf_list_installed_timeout_raises_not_hangs():
    """A hung dnf list --installed subprocess must raise, not hang (audit finding B1),
    and must not report an empty install list as if the query had succeeded."""
    async def run_test():
        manager = DnfManager()

        mock_proc = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(DriverError):
                    await manager.list_installed()

    asyncio.run(run_test())


def test_dnf_check_updates_kills_leaked_json_attempt_before_fallback():
    """A timed-out `dnf check-update --json` attempt must be killed, not abandoned —
    otherwise it lingers in the background holding DNF's system-repository lock,
    which blocks the fallback check right below (and any later upgrade command)
    from ever acquiring it. This reproduces a real-world lock-contention bug where
    the leaked --json process was still holding the lock when the user's very next
    DNF upgrade tried to run."""
    async def run_test():
        manager = DnfManager()

        mock_json_proc = AsyncMock()
        mock_json_proc.returncode = None  # still "running" when we give up on it

        mock_fallback_proc = AsyncMock()
        mock_fallback_proc.returncode = 100
        mock_fallback_proc.communicate.return_value = (
            b"package1.x86_64                     1.1.0-1.fc40                    updates\n",
            b""
        )

        def create_subprocess_exec_side_effect(*args, **kwargs):
            return mock_json_proc if "--json" in args else mock_fallback_proc

        call_count = 0

        async def wait_for_side_effect(coro, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                coro.close()
                raise asyncio.TimeoutError
            return await coro

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec_side_effect):
            with patch("asyncio.wait_for", side_effect=wait_for_side_effect):
                updates = await manager._query_updates()

        mock_json_proc.kill.assert_called_once()
        mock_json_proc.wait.assert_called_once()
        assert len(updates) == 1
        assert updates[0]["name"] == "package1"

    asyncio.run(run_test())


def test_dnf_check_updates_fallback():
    """Test check_updates falls back to standard dnf check-update quiet output."""
    async def run_test():
        manager = DnfManager()

        mock_json_proc = AsyncMock()
        mock_json_proc.returncode = 1
        mock_json_proc.communicate.return_value = (b"", b"error or unsupported option")

        mock_fallback_proc = AsyncMock()
        mock_fallback_proc.returncode = 100
        mock_fallback_proc.communicate.return_value = (
            b"Last metadata expiration check: 0:05:00 ago.\n"
            b"package1.x86_64                     1.1.0-1.fc40                    updates\n",
            b""
        )

        def create_subprocess_exec_side_effect(*args, **kwargs):
            if "--json" in args:
                return mock_json_proc
            elif "--quiet" in args:
                return mock_fallback_proc
            raise ValueError(f"Unexpected subprocess call: {args}")

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec_side_effect) as mock_exec:
            updates = await manager._query_updates()
            assert mock_exec.call_count == 2

        assert len(updates) == 1
        assert updates[0] == {"name": "package1", "current": "Installed", "new": "1.1.0-1.fc40"}

    asyncio.run(run_test())


def test_dnf_check_updates_flags_vendor_change_blocked():
    """With allow_vendor_change off, `dnf upgrade` silently skips a vendor-changing upgrade and
    exits 0, so the scan must flag it (not offer it as a normal upgrade) unless the user has
    allowlisted that package, in which case the upgrade command passes --allow-vendor-change."""
    from unittest.mock import MagicMock

    def run_test():
        manager = DnfManager()
        outputs = {
            "--dump-main-config": b"allow_vendor_change = 0\n",
            "repoquery": b"vhs charmbracelet\nbash Fedora Project\n",
            "-q": b"vhs Fedora Project\nbash Fedora Project\n",
        }

        def fake_exec(*args, **kwargs):
            proc = AsyncMock()
            proc.communicate.return_value = (next(v for k, v in outputs.items() if k in args), b"")
            return proc

        def scan(allowlist):
            settings = MagicMock()
            settings.get.return_value = allowlist
            updates = [{"name": "vhs", "current": "Installed", "new": "0.12.1-1"},
                       {"name": "bash", "current": "Installed", "new": "5.3-2"}]
            with patch("app.core.drivers.dnf.get_settings", return_value=settings), \
                 patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                return asyncio.run(manager._mark_vendor_blocked(updates)), settings

        updates, _ = scan([])
        assert updates[0]["blocked"] == "vendor change: Fedora Project → charmbracelet"
        assert "blocked" not in updates[1]

        updates, settings = scan(["vhs"])
        assert not any("blocked" in u for u in updates)
        with patch("app.core.drivers.dnf.get_settings", return_value=settings):
            assert "--allow-vendor-change" in manager.get_upgrade_command(["vhs", "bash"])
            assert "--allow-vendor-change" not in manager.get_upgrade_command(["bash"])

        outputs["--dump-main-config"] = b"allow_vendor_change = 1\n"
        updates, _ = scan([])
        assert not any("blocked" in u for u in updates)

    run_test()
