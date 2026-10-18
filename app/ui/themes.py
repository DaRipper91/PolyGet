"""Colour themes for the GUI and the TUI.

Every colour in PolyGet's stylesheets is written as a Catppuccin Mocha hex (plus a few older
Tailwind tints). A theme is a set of named roles; `themed()` rewrites each Mocha hex in a
stylesheet or HTML snippet to the active theme's value for the same role, so no widget code
needs to know which theme is active. With the Mocha theme and no accent override the text
comes back unchanged.

Roles follow Catppuccin's names (crust … text for the surfaces, blue … pink for accents), since
the app was designed in Mocha. Themes that don't define the rarer accents derive them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DEFAULT_THEME = "mocha"
SYSTEM = "system"
DEFAULT_DARK = "mocha"
DEFAULT_LIGHT = "latte"
ACCENT_ROLES = ("blue", "mauve", "teal", "green", "peach", "pink", "red", "yellow", "sky")

_SURFACES = ("crust", "mantle", "base", "surface0", "surface1", "surface2",
             "overlay0", "overlay1", "subtext0", "text")
_ACCENTS = ("blue", "mauve", "green", "yellow", "peach", "red", "teal", "sky", "pink")


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    """`a` blended toward `b` by `t` (0 = a, 1 = b)."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#{:02x}{:02x}{:02x}".format(
        round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


def luminance(hex_: str) -> float:
    def ch(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hex_)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    light: bool
    roles: dict[str, str] = field(repr=False)


def _theme(key: str, name: str, light: bool, surfaces: str, accents: str, **extra: str) -> Theme:
    roles = dict(zip(_SURFACES, ("#" + h for h in surfaces.split())))
    roles.update(zip(_ACCENTS, ("#" + h for h in accents.split())))
    roles.update({k: "#" + v for k, v in extra.items()})
    r = roles
    # Accents double as text colours (version numbers, "scan failed", "Needs admin password").
    # Where a canonical palette's accent is too faint on its own background, pull it toward
    # the text colour until it reads at 4.5:1. Most themes are untouched.
    for name in _ACCENTS:
        for _ in range(10):
            if contrast(r[name], r["base"]) >= 4.5:
                break
            # Darken toward black on light themes (keeps the hue); lighten toward text on dark.
            r[name] = mix(r[name], "#000000" if light else r["text"], 0.12)
    roles.setdefault("lavender", mix(r["blue"], r["text"], 0.35))
    roles.setdefault("maroon", mix(r["red"], r["peach"], 0.4))
    roles.setdefault("sapphire", mix(r["blue"], r["sky"], 0.5))
    roles.setdefault("flamingo", mix(r["pink"], r["red"], 0.35))
    roles.setdefault("rosewater", mix(r["pink"], r["text"], 0.5))
    roles.setdefault("indigo", mix(r["blue"], r["mauve"], 0.5))
    roles.setdefault("bright", r["text"])
    # Text drawn on a filled accent (buttons, badges): dark on dark themes' pastel accents,
    # white on light themes' saturated ones.
    roles.setdefault("on_accent", "#ffffff" if light else r["crust"])
    return Theme(key, name, light, roles)


THEMES: dict[str, Theme] = {t.key: t for t in (
    _theme("mocha", "Catppuccin Mocha", False,
           "11111b 181825 1e1e2e 313244 45475a 585b70 6c7086 7f849c a6adc8 cdd6f4",
           "89b4fa cba6f7 a6e3a1 f9e2af fab387 f38ba8 94e2d5 89dceb f5c2e7",
           lavender="b4befe", maroon="eba0ac", sapphire="74c7ec", flamingo="f2cdcd",
           rosewater="f5e0dc", indigo="7287fd", bright="ffffff"),
    _theme("macchiato", "Catppuccin Macchiato", False,
           "181926 1e2030 24273a 363a4f 494d64 5b6078 6e738d 8087a2 a5adcb cad3f5",
           "8aadf4 c6a0f6 a6da95 eed49f f5a97f ed8796 8bd5ca 91d7e3 f5bde6",
           lavender="b7bdf8", maroon="ee99a0", sapphire="7dc4e4", flamingo="f0c6c6", rosewater="f4dbd6"),
    _theme("frappe", "Catppuccin Frappé", False,
           "232634 292c3c 303446 414559 51576d 626880 737994 838ba7 a5adce c6d0f5",
           "8caaee ca9ee6 a6d189 e5c890 ef9f76 e78284 81c8be 99d1db f4b8e4",
           lavender="babbf1", maroon="ea999c", sapphire="85c1dc", flamingo="eebebe", rosewater="f2d5cf"),
    _theme("latte", "Catppuccin Latte", True,
           "dce0e8 e6e9ef eff1f5 ccd0da bcc0cc acb0be 9ca0b0 8c8fa1 6c6f85 4c4f69",
           "1e66f5 8839ef 40a02b df8e1d fe640b d20f39 179299 04a5e5 ea76cb",
           lavender="7287fd", maroon="e64553", sapphire="209fb5", flamingo="dd7878", rosewater="dc8a78"),
    _theme("nord", "Nord", False,
           "242933 292e39 2e3440 3b4252 434c5e 4c566a 616e88 7b88a1 d8dee9 eceff4",
           "81a1c1 b48ead a3be8c ebcb8b d08770 bf616a 8fbcbb 88c0d0 d6a3c9"),
    _theme("gruvbox-dark", "Gruvbox Dark", False,
           "1d2021 242424 282828 3c3836 504945 665c54 7c6f64 928374 bdae93 ebdbb2",
           "83a598 d3869b b8bb26 fabd2f fe8019 fb4934 8ec07c 7daea3 d3869b"),
    _theme("gruvbox-light", "Gruvbox Light", True,
           "ebdbb2 f2e5bc fbf1c7 d5c4a1 bdae93 a89984 928374 7c6f64 504945 3c3836",
           "076678 8f3f71 79740e b57614 af3a03 9d0006 427b58 458588 b16286"),
    _theme("tokyo-night", "Tokyo Night", False,
           "13141c 16161e 1a1b26 292e42 3b4261 414868 565f89 737aa2 a9b1d6 c0caf5",
           "7aa2f7 bb9af7 9ece6a e0af68 ff9e64 f7768e 73daca 7dcfff e5a1d6"),
    _theme("dracula", "Dracula", False,
           "191a21 21222c 282a36 343746 44475a 525568 6272a4 7b86b8 d6d6e0 f8f8f2",
           "bd93f9 ff79c6 50fa7b f1fa8c ffb86c ff5555 8be9fd 8be9fd ff79c6"),
    _theme("one-dark", "One Dark", False,
           "1b1f27 21252b 282c34 2c313c 3e4451 4b5263 5c6370 7f848e abb2bf d7dae0",
           "61afef c678dd 98c379 e5c07b d19a66 e06c75 56b6c2 56b6c2 e599c8"),
    _theme("rose-pine", "Rosé Pine", False,
           "12101a 16141f 191724 26233a 393552 44415a 6e6a86 908caa c4c1db e0def4",
           "9ccfd8 c4a7e7 8fb8a8 f6c177 ebbcba eb6f92 56949f 9ccfd8 ebbcba"),
    _theme("rose-pine-dawn", "Rosé Pine Dawn", True,
           "f2e9e1 f6eee6 faf4ed dfdad9 cecacd b9b4bd 9893a5 797593 6e6a86 575279",
           "286983 907aa9 4b8c6f ea9d34 d7827e b4637a 56949f 56949f d7827e"),
    _theme("solarized-dark", "Solarized Dark", False,
           "00212b 00262f 002b36 073642 0b4552 18505d 586e75 657b83 93a1a1 eee8d5",
           "268bd2 6c71c4 859900 b58900 cb4b16 dc322f 2aa198 3fa8d6 d33682"),
    _theme("solarized-light", "Solarized Light", True,
           "eee8d5 f5efdc fdf6e3 e4ddc8 d6cfb9 c5bea8 93a1a1 839496 586e75 073642",
           "268bd2 6c71c4 859900 b58900 cb4b16 dc322f 2aa198 3fa8d6 d33682"),
    _theme("everforest", "Everforest Dark", False,
           "232a2e 293136 2d353b 343f44 475258 4f585e 7a8478 859289 9da9a0 d3c6aa",
           "7fbbb3 d699b6 a7c080 dbbc7f e69875 e67e80 83c092 7fbbb3 d699b6"),
    _theme("kanagawa", "Kanagawa", False,
           "16161d 1a1a22 1f1f28 2a2a37 363646 54546d 727169 8a8980 c8c093 dcd7ba",
           "7e9cd8 957fb8 98bb6c e6c384 ffa066 e46876 7aa89f 7fb4ca d27e99"),
    _theme("synthwave", "Synthwave", False,
           "0d0019 12002b 1a0a33 2b1650 3d1f6b 4e2a85 6f5a96 8a6fb3 c9b8e8 f2e9ff",
           "22d3ee f0369a 72f1b8 fde047 ff8b39 fe4450 36f9f6 22d3ee ff7edb"),
)}


# --- How the source colours map onto roles -----------------------------------------------------

# Every Mocha hex the stylesheets use, by role.
_MOCHA = THEMES["mocha"].roles
_SOURCE_ROLE: dict[str, str] = {}
for _role, _hex in _MOCHA.items():
    if _role != "on_accent":
        _SOURCE_ROLE.setdefault(_hex, _role)

# Older Tailwind colours still in the code: (role, blended toward base by t). The tints are
# badge/row backgrounds, so they're recomputed per theme rather than kept as fixed hexes.
_SOURCE_DERIVED: dict[str, tuple[str, float]] = {
    "#6ee7b7": ("green", 0.0), "#064e3b": ("green", 0.72),
    "#fca5a5": ("red", 0.0), "#7f1d1d": ("red", 0.72),
    "#93c5fd": ("blue", 0.0), "#1e3a8a": ("blue", 0.72),
    "#d8b4fe": ("mauve", 0.0), "#581c87": ("mauve", 0.72),
    "#9ca3af": ("subtext0", 0.0), "#374151": ("surface0", 0.0),
    "#2a1c26": ("red", 0.88), "#5c2d3e": ("red", 0.62),
    # The TUI's own purple palette (app/ui/tui.tcss).
    "#0d0714": ("crust", 0.0), "#08030c": ("crust", 0.0), "#1a0b2e": ("mantle", 0.0),
    "#0f0717": ("base", 0.0), "#2e1a47": ("surface0", 0.0), "#f1eef6": ("text", 0.0),
    "#e2d9f3": ("subtext0", 0.0), "#8b5cf6": ("blue", 0.0), "#a78bfa": ("lavender", 0.0),
    "#c084fc": ("pink", 0.0), "#fbbf24": ("yellow", 0.0), "#34d399": ("green", 0.0),
    "#94a3b8": ("overlay1", 0.0), "#60a5fa": ("blue", 0.0), "#38bdf8": ("sky", 0.0),
}

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
# `color:` (not background-color/border-color) set to crust means "text on a filled accent".
_ON_ACCENT_MARK = "\x00on-accent\x00"
_ON_ACCENT = re.compile(r"(?<![-\w])(color\s*:\s*)#11111b\b", re.IGNORECASE)


@dataclass
class Active:
    theme: Theme
    accent: str | None = None  # an ACCENT_ROLES name, or None for the theme's own blue

    def role(self, name: str) -> str:
        roles = self.theme.roles
        if self.accent and self.accent != "blue":
            if name == "blue":
                return roles[self.accent]
            if name == "lavender":
                return mix(roles[self.accent], roles["text"], 0.35)
        return roles[name]

    @property
    def is_identity(self) -> bool:
        return self.theme.key == "mocha" and self.accent in (None, "blue")


_active = Active(THEMES[DEFAULT_THEME])


def active() -> Active:
    return _active


def set_active(theme_key: str, accent: str | None = None) -> Active:
    global _active
    _active = Active(THEMES.get(theme_key, THEMES[DEFAULT_THEME]),
                     accent if accent in ACCENT_ROLES else None)
    return _active


def resolve(choice: str, system_is_dark: bool, dark: str = DEFAULT_DARK, light: str = DEFAULT_LIGHT) -> str:
    """The theme key to use for a Settings choice; "system" picks the dark or light one."""
    if choice == SYSTEM:
        key = dark if system_is_dark else light
    else:
        key = choice
    return key if key in THEMES else DEFAULT_THEME


def themed(text: str, theme: Active | None = None, force: bool = False) -> str:
    """Rewrite Mocha colours in a stylesheet/HTML snippet into the active theme's.

    `force` also maps when the theme is Mocha itself: the TUI's stylesheet is written in its
    own purple palette, which Mocha would otherwise leave as is.
    """
    t = theme or _active
    if not text or (t.is_identity and not force):
        return text
    roles_base = t.role("base")
    # Mark text-on-accent first, fill it in last, so its value is never mapped a second time.
    text = _ON_ACCENT.sub(lambda m: m.group(1) + _ON_ACCENT_MARK, text)

    def swap(m: re.Match) -> str:
        src = m.group(0).lower()
        if src in _SOURCE_ROLE:
            return t.role(_SOURCE_ROLE[src])
        if src in _SOURCE_DERIVED:
            role, toward_base = _SOURCE_DERIVED[src]
            value = t.role(role)
            return mix(value, roles_base, toward_base) if toward_base else value
        return m.group(0)

    return _HEX.sub(swap, text).replace(_ON_ACCENT_MARK, t.role("on_accent"))
