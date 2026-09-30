import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.apt import AptManager
from app.core.drivers.dnf import DnfManager
from app.core.drivers.flatpak import FlatpakManager
from app.core.manager import DriverError

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


# ── Failure must not read as "none configured" ─────────────────────────────────
#
# The Repositories page exists to show the system's real state. A failed
# `dnf repolist` used to render as an empty list, i.e. "you have no
# repositories", which is a false claim. These lock in the DriverError contract.


@pytest.mark.parametrize(
    "cls", [DnfManager, FlatpakManager], ids=["dnf", "flatpak"]
)
def test_list_repos_nonzero_exit_raises(cls):
    """A nonzero exit must raise, not report zero configured repositories."""
    manager = cls()

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"error: cannot read repo config")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(DriverError):
                await manager.list_repos()

    asyncio.run(run_test())


@pytest.mark.parametrize(
    "cls", [DnfManager, FlatpakManager], ids=["dnf", "flatpak"]
)
def test_list_repos_timeout_raises_not_hangs(cls):
    """A hung query must raise rather than hang, and must not read as empty."""
    manager = cls()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(DriverError):
                    await manager.list_repos()

    asyncio.run(run_test())


@pytest.mark.parametrize(
    "cls", [DnfManager, FlatpakManager], ids=["dnf", "flatpak"]
)
def test_list_repos_missing_binary_raises(cls):
    """A missing binary must raise, not report zero configured repositories."""
    manager = cls()

    async def run_test():
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("nope")):
            with pytest.raises(DriverError):
                await manager.list_repos()

    asyncio.run(run_test())


@pytest.mark.parametrize(
    "cls", [DnfManager, FlatpakManager], ids=["dnf", "flatpak"]
)
def test_list_repos_empty_output_is_a_true_empty(cls):
    """A successful query with no output must still return [] — that is a real answer."""
    manager = cls()

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            assert await manager.list_repos() == []

    asyncio.run(run_test())


def test_apt_list_repos_missing_sources_file_is_a_true_empty():
    """APT parses config files rather than shelling out, so an absent sources file
    genuinely means 'no repos configured' and must NOT raise. This is the case that
    justifies reading files instead of shelling out."""
    manager = AptManager()

    async def run_test():
        with patch("app.core.drivers.apt.glob.glob", return_value=[]):
            with patch("builtins.open", side_effect=FileNotFoundError("/etc/apt/sources.list")):
                assert await manager.list_repos() == []

    asyncio.run(run_test())


def test_base_class_list_repos_is_unsupported_not_failed():
    """A manager with no repo concept raises NotImplementedError, which the CLI gather
    layer already classifies as 'unsupported' rather than a failure."""
    from app.core.manager import PackageManager

    class NoRepos(PackageManager):
        name = "NoRepos"

    manager = NoRepos()
    assert manager.supports_repos is False

    async def run_test():
        with pytest.raises(NotImplementedError):
            await manager.list_repos()

    asyncio.run(run_test())
