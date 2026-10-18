"""Settings hint labels (password status, log path, empty lists) must stay readable on the window
background: #6c7086 was 3.4:1 on #1e1e2e, below the 4.5:1 that small text needs."""

import re
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "app" / "ui" / "main_window.py").read_text()
BASE = "#1e1e2e"


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_settings_hint_labels_meet_aa_on_base():
    for name in ("lbl_pw_status", "lbl_debug_path"):
        colour = re.search(name + r'\.setStyleSheet\("color: (#[0-9a-fA-F]{6})', SOURCE).group(1)
        assert _contrast(colour, BASE) >= 4.5, f"{name} uses {colour}"


def test_empty_list_notes_meet_aa_on_base():
    colour = re.search(r'lbl = QLabel\(empty\)\s+lbl\.setStyleSheet\("color: (#[0-9a-fA-F]{6})', SOURCE).group(1)
    assert _contrast(colour, BASE) >= 4.5
