import asyncio
import json
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


def test_ignore_store_concurrent_add_remove_no_corruption(tmp_path: Path):
    """Concurrent add()/remove() calls from multiple threads must not corrupt the file."""
    test_file = tmp_path / "ignored.json"
    store = IgnoreStore(path=test_file)

    async def add_many(prefix: str, count: int) -> None:
        for i in range(count):
            store.add(prefix, f"pkg{i}")

    async def remove_even(prefix: str, count: int) -> None:
        for i in range(count):
            if i % 2 == 0:
                store.remove(prefix, f"pkg{i}")

    async def main() -> None:
        await asyncio.gather(
            add_many("thread_a", 30),
            add_many("thread_b", 30),
            remove_even("thread_a", 30),
        )

    asyncio.run(main())

    # File must still be valid JSON.
    raw = json.loads(test_file.read_text(encoding="utf-8"))
    entries = {(item["manager"], item["package"]) for item in raw}

    # thread_a even-numbered pkgs were added then removed; odd ones remain.
    for i in range(30):
        pkg = f"pkg{i}"
        if i % 2 == 0:
            assert ("thread_a", pkg) not in entries, f"thread_a {pkg} should have been removed"
        else:
            assert ("thread_a", pkg) in entries, f"thread_a {pkg} should still be present"

    # All thread_b pkgs were added and never removed.
    for i in range(30):
        assert ("thread_b", f"pkg{i}") in entries

