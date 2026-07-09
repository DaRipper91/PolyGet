import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.dnf import DnfManager
from app.core.drivers.flatpak import FlatpakManager

def test_dnf_repository_management():
    manager = DnfManager()
    assert manager.supports_repos is True

    # 1. Test get_add_repo_command
    assert manager.get_add_repo_command("group/project") == ["pkexec", "dnf", "copr", "enable", "-y", "group/project"]
    assert manager.get_add_repo_command("https://example.com/repo.repo") == ["pkexec", "dnf", "config-manager", "--add-repo", "https://example.com/repo.repo"]
    assert manager.get_remove_repo_command("my-repo-id") == ["pkexec", "dnf", "config-manager", "--set-disabled", "my-repo-id"]

    # 2. Test list_repos parsing
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"repo id                                           repo name                                           status\n"
            b"fedora                                            Fedora 40                                           enabled\n"
            b"fedora-testing                                    Fedora testing                                      disabled\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            repos = await manager.list_repos()
            
        assert len(repos) == 2
        assert repos[0] == {"id": "fedora", "name": "Fedora 40", "url": "", "enabled": True}
        assert repos[1] == {"id": "fedora-testing", "name": "Fedora testing", "url": "", "enabled": False}

    asyncio.run(run_test())

def test_flatpak_repository_management():
    manager = FlatpakManager()
    assert manager.supports_repos is True

    # 1. Test get_add_repo_command
    assert manager.get_add_repo_command("flathub") == ["flatpak", "remote-add", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"]
    assert manager.get_add_repo_command("https://example.com/custom.flatpakrepo") == ["flatpak", "remote-add", "--if-not-exists", "https://example.com/custom.flatpakrepo", "https://example.com/custom.flatpakrepo"]
    assert manager.get_remove_repo_command("flathub-beta") == ["flatpak", "remote-delete", "flathub-beta"]

    # 2. Test list_repos parsing
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"flathub\thttps://dl.flathub.org/repo/\tuser\n"
            b"fedora\toci+https://registry.fedoraproject.org\tsystem,oci,disabled\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            repos = await manager.list_repos()
            
        assert len(repos) == 2
        assert repos[0] == {"id": "flathub", "name": "flathub", "url": "https://dl.flathub.org/repo/", "enabled": True}
        assert repos[1] == {"id": "fedora", "name": "fedora", "url": "oci+https://registry.fedoraproject.org", "enabled": False}

    asyncio.run(run_test())
