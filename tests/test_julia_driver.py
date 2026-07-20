import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.julia import JuliaManager

def test_julia_list_installed():
    manager = JuliaManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"DataFrames\n"
            b"JSON\n"
            b"DataFrames\n", # test duplication filtering
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["DataFrames", "JSON"]

    asyncio.run(run_test())


def test_julia_commands_keep_package_names_out_of_source():
    manager = JuliaManager()
    package = 'evil"); run(`touch /tmp/polyget-audit`); #'

    install = manager.get_install_command(package)
    upgrade = manager.get_upgrade_command([package])

    assert install == ["julia", "-e", "using Pkg; Pkg.add(ARGS[1])", "--", package]
    assert upgrade == ["julia", "-e", "using Pkg; Pkg.update(ARGS)", "--", package]
    assert package not in install[2]
    assert package not in upgrade[2]
