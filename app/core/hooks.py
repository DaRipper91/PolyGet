"""User commands that run before/after upgrades and removals (Topgrade-style pre/post hooks).

Stored in settings under "hooks.list". Each hook is an argv list, never a shell string, so the
no-shell rule holds for user-supplied commands too. Typical use: a btrfs snapshot before a system
upgrade (`pkexec snapper create -d polyget`), or `flatpak repair` after one.
"""

from typing import Any

from app.core.settings_store import get_settings

WHEN = ("pre", "post")
OPERATIONS = ("upgrade", "remove")
_KEY = "hooks.list"


def load_hooks() -> list[dict[str, Any]]:
    hooks = get_settings().get(_KEY, []) or []
    return [h for h in hooks if isinstance(h, dict) and h.get("when") in WHEN and h.get("command")]


def add_hook(when: str, command: list[str], managers: list[str] | None = None,
             operations: list[str] | None = None) -> dict[str, Any]:
    if when not in WHEN:
        raise ValueError(f"when must be one of {', '.join(WHEN)}")
    if not command:
        raise ValueError("a hook needs a command")
    ops = operations or list(OPERATIONS)
    if bad := [o for o in ops if o not in OPERATIONS]:
        raise ValueError(f"unknown operation(s): {', '.join(bad)}")
    hook = {"when": when, "command": list(command), "managers": list(managers or []), "on": ops}
    get_settings().set(_KEY, load_hooks() + [hook])
    return hook


def remove_hook(index: int) -> dict[str, Any]:
    hooks = load_hooks()
    if not 0 <= index < len(hooks):
        raise IndexError(f"no hook #{index + 1}")
    removed = hooks.pop(index)
    get_settings().set(_KEY, hooks)
    return removed


def hooks_for(when: str, operation: str, manager_names: list[str]) -> list[dict[str, Any]]:
    """Hooks to run for an operation touching these managers. A hook with no managers listed
    applies to every manager; otherwise it runs if any listed manager (case-insensitive) is involved."""
    involved = {m.lower() for m in manager_names}
    return [
        h for h in load_hooks()
        if h["when"] == when and operation in h.get("on", OPERATIONS)
        and (not h.get("managers") or involved & {m.lower() for m in h["managers"]})
    ]
