import pytest
from unittest.mock import mock_open, patch
from app.core.distro import get_distro_family

def test_get_distro_family_fedora():
    get_distro_family.cache_clear()
    mock_data = 'ID=fedora\nID_LIKE="rhel centos"'
    with patch("builtins.open", mock_open(read_data=mock_data)):
        assert get_distro_family() == "fedora"

def test_get_distro_family_cachyos():
    get_distro_family.cache_clear()
    mock_data = 'ID=cachyos\nID_LIKE="arch"'
    with patch("builtins.open", mock_open(read_data=mock_data)):
        assert get_distro_family() == "arch"

def test_get_distro_family_unknown():
    get_distro_family.cache_clear()
    mock_data = 'ID=gentoo\nID_LIKE="something"'
    with patch("builtins.open", mock_open(read_data=mock_data)):
        assert get_distro_family() == "unknown"

def test_get_distro_family_unquoted():
    get_distro_family.cache_clear()
    mock_data = 'ID=debian\nID_LIKE=ubuntu'
    with patch("builtins.open", mock_open(read_data=mock_data)):
        assert get_distro_family() == "debian"
