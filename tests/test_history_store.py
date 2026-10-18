from pathlib import Path
from app.core.history_store import record_removal, record_upgrade, load_history


def test_history_store_roundtrip(tmp_path: Path):
    test_file = tmp_path / "history.jsonl"
    record_upgrade("Cargo", ["satty"], True, path=test_file)
    record_upgrade("DNF", ["librepo"], False, path=test_file)

    history = load_history(path=test_file)
    assert len(history) == 2
    assert history[0]["manager"] == "DNF"
    assert history[0]["success"] is False
    assert history[1]["manager"] == "Cargo"
    assert history[1]["success"] is True


def test_removals_are_logged_with_their_action(tmp_path: Path):
    test_file = tmp_path / "history.jsonl"
    record_upgrade("Cargo", ["satty"], True, path=test_file)
    record_removal("Pacman", ["ripgrep"], True, path=test_file, not_removed=["ripgrep"])
    removal, upgrade = load_history(path=test_file)
    assert removal["action"] == "remove" and removal["success"] is False
    assert removal["not_removed"] == ["ripgrep"]
    # Entries written before removals existed carry no action; they read back as upgrades.
    assert upgrade["action"] == "upgrade"
