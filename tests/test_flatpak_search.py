import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.flatpak import FlatpakManager

def test_flatpak_search_packages():
    manager = FlatpakManager()

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"GNU Image Manipulation Program\tCreate images and edit photographs\torg.gimp.GIMP\t2.10.32\tflathub\n"
            b"Firefox\tWeb browser\torg.mozilla.firefox\t115.0\tflathub,fedora\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("gimp")
            
        assert len(results) == 2
        assert results[0] == {
            "name": "GNU Image Manipulation Program",
            "description": "Create images and edit photographs",
            "id": "org.gimp.GIMP",
            "version": "2.10.32",
            "remote": "flathub"
        }
        assert results[1]["name"] == "Firefox"
        assert results[1]["remote"] == "flathub"

    asyncio.run(run_test())
