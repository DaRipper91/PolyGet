from pathlib import Path
from app.core.ignore_store import IgnoreStore


def test_ignore_store_roundtrip(tmp_path: Path):
    test_file = tmp_path / "ignored.json"
    store = IgnoreStore(path=test_file)
    assert not store.is_ignored("Cargo", "satty")

    store.add("Cargo", "satty")
    assert store.is_ignored("Cargo", "satty")

    store2 = IgnoreStore(path=test_file)
    assert store2.is_ignored("Cargo", "satty")

    store2.remove("Cargo", "satty")
    assert not store2.is_ignored("Cargo", "satty")
