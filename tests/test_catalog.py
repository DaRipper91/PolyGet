import pytest
from unittest.mock import patch
from app.core.catalog import load_catalog, CatalogEntry

def test_load_catalog():
    """Verify that catalog loading works and returns at least 23 entries with valid categories."""
    entries = load_catalog()
    assert len(entries) >= 23
    
    valid_categories = {"System", "Universal", "Language/Dev"}
    for entry in entries:
        assert entry.category in valid_categories, f"Invalid category {entry.category} for entry {entry.name}"
    
    # Check specific fields of some entries
    dnf_entry = next((e for e in entries if e.id == "dnf"), None)
    assert dnf_entry is not None
    assert dnf_entry.name == "DNF"
    assert dnf_entry.category == "System"
    
    flatpak_entry = next((e for e in entries if e.id == "flatpak"), None)
    assert flatpak_entry is not None
    assert flatpak_entry.category == "Universal"

def test_catalog_self_install_command():
    """Test get_self_install_command outputs correctly based on mocked distro family."""
    entry = CatalogEntry(
        id="test-mgr",
        name="Test",
        category="TestCat",
        description="test desc",
        icon="icon",
        binary="testbin",
        has_driver=False,
        self_install={
            "fedora": ["dnf", "install", "test-mgr"],
            "arch": ["pacman", "-S", "test-mgr"]
        }
    )

    with patch("app.core.catalog.get_distro_family", return_value="fedora"):
        assert entry.get_self_install_command() == ["dnf", "install", "test-mgr"]

    with patch("app.core.catalog.get_distro_family", return_value="arch"):
        assert entry.get_self_install_command() == ["pacman", "-S", "test-mgr"]

    with patch("app.core.catalog.get_distro_family", return_value="alpine"):
        assert entry.get_self_install_command() is None

def test_catalog_driver_consistency():
    """Verify that every catalog entry with has_driver=True has a corresponding registered PackageManager."""
    from app.core.manager import _REGISTRY
    import app.core.drivers
    
    entries = load_catalog()
    registered_names = [cls.name for cls in _REGISTRY]
    
    for entry in entries:
        if entry.has_driver:
            assert entry.name in registered_names, f"Catalog entry {entry.name} has has_driver=True but no driver is registered under that name."
