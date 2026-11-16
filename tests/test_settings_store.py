import asyncio
import json
from pathlib import Path

from app.core.settings_store import SettingsStore


def test_settings_store_roundtrip(tmp_path: Path):
    test_file = tmp_path / "settings.json"
    store = SettingsStore(path=test_file)

    assert store.get("version_scan.strict_matching") is True
    assert store.get("missing.key", "default") == "default"

    store.set("version_scan.strict_matching", False)
    assert store.get("version_scan.strict_matching") is False

    # Persist across instances
    store2 = SettingsStore(path=test_file)
    assert store2.get("version_scan.strict_matching") is False


def test_settings_store_alias_map(tmp_path: Path):
    test_file = tmp_path / "settings.json"
    store = SettingsStore(path=test_file)

    store.set_alias("ripgrep", "Pacman", "ripgrep")
    store.set_alias("ripgrep", "NPM", "ripgrep-all")

    assert store.resolve_name("Pacman", "ripgrep") == "ripgrep"
    assert store.resolve_name("NPM", "ripgrep-all") == "ripgrep"
    assert store.reverse_resolve("ripgrep", "Pacman") == "ripgrep"

    store.remove_alias("ripgrep", "Pacman")
    assert store.reverse_resolve("ripgrep", "Pacman") is None
    assert store.resolve_name("Pacman", "ripgrep") == "ripgrep"


def test_settings_store_skip_version(tmp_path: Path):
    test_file = tmp_path / "settings.json"
    store = SettingsStore(path=test_file)

    store.skip_version("NPM", "lodash", "4.17.20")
    assert store.is_skipped("NPM", {"name": "lodash", "new": "4.17.20"})
    assert not store.is_skipped("NPM", {"name": "lodash", "new": "4.17.21"})
    assert store.skipped_version("NPM", "lodash") == "4.17.20"

    store.unskip_version("NPM", "lodash")
    assert store.is_skipped("NPM", {"name": "lodash", "new": "4.17.20"}) is False
    assert store.skipped_version("NPM", "lodash") is None


def test_settings_store_project_dirs(tmp_path: Path):
    test_file = tmp_path / "settings.json"
    store = SettingsStore(path=test_file)

    assert store.add_project_dir("/tmp/proj1") is True
    assert store.add_project_dir("/tmp/proj1") is False  # duplicate
    assert store.add_project_dir("/tmp/proj2") is True
    assert store.get_project_dirs() == ["/tmp/proj1", "/tmp/proj2"]

    assert store.remove_project_dir("/tmp/proj1") is True
    assert store.remove_project_dir("/tmp/proj1") is False  # not tracked
    assert store.get_project_dirs() == ["/tmp/proj2"]


def test_settings_store_concurrent_set_no_lost_updates(tmp_path: Path):
    """Concurrent set() calls from multiple threads must not lose updates."""
    test_file = tmp_path / "settings.json"
    store = SettingsStore(path=test_file)

    async def set_many(prefix: str, count: int) -> None:
        for i in range(count):
            store.set(f"{prefix}.{i}", i)

    async def main() -> None:
        await asyncio.gather(
            set_many("thread_a", 20),
            set_many("thread_b", 20),
        )

    asyncio.run(main())

    # Every key written by either thread must be present with its correct value.
    for i in range(20):
        assert store.get(f"thread_a.{i}") == i
        assert store.get(f"thread_b.{i}") == i

    # File must still be valid JSON.
    raw = json.loads(test_file.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
