import asyncio
import pytest
from unittest.mock import AsyncMock, mock_open, patch
from app.core.drivers.apt import AptManager


def test_apt_driver_imports():
    """Validate that the AptManager driver can be imported and instantiated."""
    manager = AptManager()
    assert manager.name == "APT"
    assert manager.category == "System"


def test_apt_driver_availability_true():
    """Test availability when apt-get binary is in PATH."""
    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        manager = AptManager()
        assert manager.is_available() is True


def test_apt_driver_availability_false():
    """Test availability when apt-get binary is NOT in PATH."""
    with patch("shutil.which", return_value=None):
        manager = AptManager()
        assert manager.is_available() is False


def test_apt_check_updates_parses_upgradable_list():
    """Test that check_updates parses real `apt list --upgradable` output correctly."""
    async def run_test():
        manager = AptManager()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            (
                b"Listing... Done\n"
                b"firefox/jammy-updates 108.0+build2-0ubuntu0.22.04.1 amd64 "
                b"[upgradable from: 107.0+build1-0ubuntu0.22.04.1]\n"
                b"vim/jammy-updates 2:8.2.3995-1ubuntu2.5 amd64 "
                b"[upgradable from: 2:8.2.3995-1ubuntu2.4]\n"
            ),
            b""
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()

        assert len(updates) == 2
        assert updates[0] == {
            "name": "firefox",
            "current": "107.0+build1-0ubuntu0.22.04.1",
            "new": "108.0+build2-0ubuntu0.22.04.1",
        }
        assert updates[1]["name"] == "vim"

    asyncio.run(run_test())


def test_apt_check_updates_empty_when_nothing_upgradable():
    """Test that check_updates returns [] when nothing is upgradable."""
    async def run_test():
        manager = AptManager()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"Listing... Done\n", b"")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()

        assert updates == []

    asyncio.run(run_test())


def test_apt_check_updates_reports_failure():
    """Test that check_updates reports a nonzero exit code to the caller."""
    async def run_test():
        manager = AptManager()
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"some error")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="APT update check failed"):
                await manager.check_updates()

    asyncio.run(run_test())


def test_apt_check_updates_reports_exception():
    """Test that check_updates reports subprocess failures to the caller."""
    async def run_test():
        manager = AptManager()
        with patch("asyncio.create_subprocess_exec", side_effect=OSError("not found")):
            with pytest.raises(RuntimeError, match="APT update check failed"):
                await manager.check_updates()

    asyncio.run(run_test())


def test_apt_get_upgrade_command_with_packages():
    """Test get_upgrade_command with specific packages."""
    manager = AptManager()
    cmd = manager.get_upgrade_command(["firefox", "vim"])
    assert cmd == ["pkexec", "apt-get", "install", "--only-upgrade", "-y", "firefox", "vim"]


def test_apt_get_upgrade_command_without_packages():
    """Test get_upgrade_command with no packages falls back to a full upgrade."""
    manager = AptManager()
    cmd = manager.get_upgrade_command()
    assert cmd == ["pkexec", "apt-get", "upgrade", "-y"]


def test_apt_get_sync_command():
    """Test get_sync_command returns the apt-get update command."""
    manager = AptManager()
    assert manager.get_sync_command() == ["pkexec", "apt-get", "update"]


def test_apt_list_installed():
    """Test list_installed parses apt-mark showmanual output."""
    async def run_test():
        manager = AptManager()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"firefox\nvim\ngit\n", b"")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()

        assert installed == ["firefox", "vim", "git"]

    asyncio.run(run_test())


def test_apt_list_installed_returns_empty_on_failure():
    """Test list_installed returns [] on nonzero exit code."""
    async def run_test():
        manager = AptManager()
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"error")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()

        assert installed == []

    asyncio.run(run_test())


def test_apt_get_install_command():
    """Test get_install_command builds a pkexec-elevated install."""
    manager = AptManager()
    assert manager.get_install_command("htop") == ["pkexec", "apt-get", "install", "-y", "htop"]


def test_apt_supports_repos():
    """Test that AptManager declares repo support."""
    assert AptManager.supports_repos is True


def test_apt_list_repos_parses_sources_list():
    """Test list_repos parses a sources.list-style file for enabled/disabled entries."""
    async def run_test():
        mock_data = (
            "deb http://archive.ubuntu.com/ubuntu jammy main restricted\n"
            "# deb-src http://archive.ubuntu.com/ubuntu jammy main restricted\n"
            "\n"
            "# A comment with nothing to do with deb entries\n"
        )

        manager = AptManager()
        with patch("app.core.drivers.apt.glob.glob", return_value=[]):
            with patch("builtins.open", mock_open(read_data=mock_data)):
                repos = await manager.list_repos()

        assert len(repos) == 2
        assert repos[0]["enabled"] is True
        assert repos[0]["id"].startswith("deb http://archive.ubuntu.com")
        assert repos[1]["enabled"] is False

    asyncio.run(run_test())


def test_apt_list_repos_handles_missing_files():
    """Test list_repos returns [] gracefully when no sources files exist."""
    async def run_test():
        manager = AptManager()
        with patch("app.core.drivers.apt.glob.glob", return_value=[]):
            with patch("builtins.open", side_effect=OSError("not found")):
                repos = await manager.list_repos()
        assert repos == []

    asyncio.run(run_test())


def test_apt_list_repos_recognizes_no_space_disabled_entry():
    """A '#deb-src ...' line (no space after #) must be surfaced as disabled, not
    silently dropped (audit finding B10)."""
    async def run_test():
        mock_data = (
            "deb http://archive.ubuntu.com/ubuntu jammy main restricted\n"
            "#deb-src http://archive.ubuntu.com/ubuntu jammy main restricted\n"
        )

        manager = AptManager()
        with patch("app.core.drivers.apt.glob.glob", return_value=[]):
            with patch("builtins.open", mock_open(read_data=mock_data)):
                repos = await manager.list_repos()

        assert len(repos) == 2
        assert repos[1]["enabled"] is False
        assert repos[1]["id"].startswith("deb-src http://archive.ubuntu.com")

    asyncio.run(run_test())


def test_apt_list_repos_parses_deb822_sources_format():
    """list_repos must parse deb822 .sources files (Ubuntu 24.04+/Debian 12+ default),
    not just legacy .list files (audit finding B9)."""
    async def run_test():
        deb822_data = (
            "Types: deb\n"
            "URIs: http://archive.ubuntu.com/ubuntu/\n"
            "Suites: noble noble-updates\n"
            "Components: main universe\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
            "\n"
            "Types: deb\n"
            "URIs: http://security.ubuntu.com/ubuntu/\n"
            "Suites: noble-security\n"
            "Components: main universe\n"
            "Enabled: no\n"
        )

        manager = AptManager()

        def fake_glob(pattern):
            if pattern.endswith("*.sources"):
                return ["/etc/apt/sources.list.d/ubuntu.sources"]
            return []

        with patch("app.core.drivers.apt.glob.glob", side_effect=fake_glob):
            with patch("builtins.open", mock_open(read_data=deb822_data)):
                repos = await manager.list_repos()

        assert len(repos) == 2
        assert repos[0]["enabled"] is True
        assert repos[0]["url"] == "http://archive.ubuntu.com/ubuntu/"
        assert repos[1]["enabled"] is False
        assert repos[1]["url"] == "http://security.ubuntu.com/ubuntu/"

    asyncio.run(run_test())


def test_apt_check_updates_strips_multiarch_qualifier():
    """check_updates() must strip the ':amd64'-style multiarch qualifier so its
    package names agree with list_installed()'s bare names (audit finding B11)."""
    async def run_test():
        manager = AptManager()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"libc6:amd64/jammy-updates 2.35-0ubuntu3.4 amd64 [upgradable from: 2.35-0ubuntu3.1]\n",
            b""
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()

        assert len(updates) == 1
        assert updates[0]["name"] == "libc6"

    asyncio.run(run_test())


def test_apt_get_add_repo_command():
    """Test get_add_repo_command builds a pkexec add-apt-repository call."""
    manager = AptManager()
    assert manager.get_add_repo_command("ppa:example/ppa") == ["pkexec", "add-apt-repository", "-y", "ppa:example/ppa"]


def test_apt_get_remove_repo_command():
    """Test get_remove_repo_command builds a pkexec removal call."""
    manager = AptManager()
    assert manager.get_remove_repo_command("ppa:example/ppa") == ["pkexec", "add-apt-repository", "--remove", "-y", "ppa:example/ppa"]


def test_apt_search_packages():
    """Test search_packages parses apt-cache search output."""
    async def run_test():
        manager = AptManager()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"htop - interactive processes viewer\nvim - Vi IMproved - enhanced vi editor\n",
            b""
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("htop")

        assert len(results) == 2
        assert results[0] == {
            "name": "htop",
            "id": "htop",
            "description": "interactive processes viewer",
            "version": "",
        }

    asyncio.run(run_test())


def test_apt_search_packages_returns_empty_on_exception():
    """Test search_packages swallows exceptions and returns []."""
    async def run_test():
        manager = AptManager()
        with patch("asyncio.create_subprocess_exec", side_effect=OSError("not found")):
            results = await manager.search_packages("htop")
        assert results == []

    asyncio.run(run_test())
