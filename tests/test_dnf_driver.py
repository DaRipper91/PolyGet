import asyncio
from unittest.mock import patch, AsyncMock

from app.core.drivers.dnf import DnfManager, _log


def test_dnf_mark_vendor_blocked_allows_vendor_change():
    """When allow_vendor_change contains the package, detection is skipped."""
    manager = DnfManager()

    async def run_test():
        updates = [{"name": "firefox", "current": "1.0", "new": "2.0"}]
        with patch.object(manager, "_query_updates", return_value=updates):
            with patch("app.core.drivers.dnf.get_settings") as mock_settings:
                mock_settings.return_value.get.return_value = ["firefox"]
                result = await manager.check_updates()
        assert result == updates
        assert "blocked" not in result[0]
        assert "vendor_change_detection_failed" not in result[0]

    asyncio.run(run_test())


def test_dnf_mark_vendor_blocked_detects_vendor_change():
    """When dnf blocks vendor changes and vendors differ, flag as blocked."""
    manager = DnfManager()

    async def run_test():
        updates = [{"name": "firefox", "current": "1.0", "new": "2.0"}]
        with patch.object(manager, "_query_updates", return_value=updates):
            with patch("app.core.drivers.dnf.get_settings") as mock_settings:
                mock_settings.return_value.get.return_value = []
                outputs = iter([
                    "allow_vendor_change = 0\n",
                    "firefox Fedora\n",
                    "firefox RPMFusion\n",
                ])
                async def fake_communicate():
                    return (next(outputs).encode(), b"")
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate = fake_communicate
                with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                    result = await manager.check_updates()
        assert result[0]["blocked"] == "vendor change: RPMFusion → Fedora"

    asyncio.run(run_test())


def test_dnf_mark_vendor_blocked_detection_failure_logged():
    """When vendor-change detection fails, error is logged and updates returned
    with vendor_change_detection_failed flag."""
    manager = DnfManager()

    async def run_test():
        updates = [{"name": "firefox", "current": "1.0", "new": "2.0"}]
        with patch.object(manager, "_query_updates", return_value=updates):
            with patch("app.core.drivers.dnf.get_settings") as mock_settings:
                mock_settings.return_value.get.return_value = []
                async def failing_communicate():
                    raise OSError("dnf not found")
                mock_proc = AsyncMock()
                mock_proc.returncode = 1
                mock_proc.communicate = failing_communicate
                with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                    logged = []
                    with patch("app.core.drivers.dnf._log", side_effect=lambda msg: logged.append(msg)):
                        result = await manager.check_updates()
        assert result == updates
        assert result[0]["vendor_change_detection_failed"] is True
        assert any("vendor-change detection failed" in msg for msg in logged)

    asyncio.run(run_test())


def test_dnf_mark_vendor_blocked_empty_names():
    """When all packages are in allow_vendor_change, returns early."""
    manager = DnfManager()

    async def run_test():
        updates = [{"name": "firefox", "current": "1.0", "new": "2.0"}]
        with patch.object(manager, "_query_updates", return_value=updates):
            with patch("app.core.drivers.dnf.get_settings") as mock_settings:
                mock_settings.return_value.get.return_value = ["firefox"]
                result = await manager.check_updates()
        assert result == updates

    asyncio.run(run_test())
