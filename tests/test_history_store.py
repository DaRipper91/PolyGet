import asyncio
import json
from pathlib import Path
from app.core.history_store import record_removal, record_upgrade, load_history


def test_history_store_roundtrip(tmp_path: Path):
    test_file = tmp_path / "history.jsonl"

    record_upgrade("NPM", ["lodash", "express"], True, path=test_file)
    record_upgrade("Pacman", ["firefox"], False, not_upgraded=["firefox"], path=test_file)
    record_upgrade("Flatpak", ["org.gnome.Calculator"], True, path=test_file)

    records = load_history(path=test_file)
    assert len(records) == 3

    assert records[0]["manager"] == "Flatpak"
    assert records[0]["packages"] == ["org.gnome.Calculator"]
    assert records[0]["success"] is True

    assert records[1]["manager"] == "Pacman"
    assert records[1]["packages"] == ["firefox"]
    assert records[1]["success"] is False
    assert records[1]["not_upgraded"] == ["firefox"]

    assert records[2]["manager"] == "NPM"
    assert records[2]["packages"] == ["lodash", "express"]
    assert records[2]["success"] is True

    # File must still be valid JSONL: one valid JSON object per line.
    lines = test_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(line)


def test_history_store_empty_when_no_file(tmp_path: Path):
    test_file = tmp_path / "history.jsonl"
    assert not test_file.exists()
    assert load_history(path=test_file) == []


def test_history_store_concurrent_record_upgrade_no_interleaving(tmp_path: Path):
    """Concurrent record_upgrade() calls must not interleave/corrupt JSONL lines."""
    test_file = tmp_path / "history.jsonl"

    async def record_many(prefix: str, count: int) -> None:
        for i in range(count):
            record_upgrade(prefix, [f"pkg{i}"], True, path=test_file)

    async def main() -> None:
        await asyncio.gather(
            record_many("thread_a", 20),
            record_many("thread_b", 20),
        )

    asyncio.run(main())

    # Every line must be valid JSON.
    lines = test_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 40

    records = [json.loads(line) for line in lines]
    managers_a = [r for r in records if r["manager"].startswith("thread_a")]
    managers_b = [r for r in records if r["manager"].startswith("thread_b")]
    assert len(managers_a) == 20
    assert len(managers_b) == 20

    for r in records:
        assert r["success"] is True
        assert len(r["packages"]) == 1


def test_removals_are_logged_with_their_action(tmp_path: Path):
    test_file = tmp_path / "history.jsonl"
    record_upgrade("Cargo", ["satty"], True, path=test_file)
    record_removal("Pacman", ["ripgrep"], True, path=test_file, not_removed=["ripgrep"])
    removal, upgrade = load_history(path=test_file)
    assert removal["action"] == "remove" and removal["success"] is False
    assert removal["not_removed"] == ["ripgrep"]
    # Entries written before removals existed carry no action; they read back as upgrades.
    assert upgrade["action"] == "upgrade"
