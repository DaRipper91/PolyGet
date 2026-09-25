"""Optional sudo password storage in the OS keyring (Secret Service / KWallet).

The password never touches a file this app owns, so nothing sensitive can end
up in the repo. When no keyring is available every call is a quiet no-op and
the TUI simply prompts each time.
"""
import getpass

try:
    import keyring
    from keyring.backends import fail
except ImportError:  # keyring not installed: remembering is just unavailable
    keyring = None

SERVICE = "polyget-sudo"


def available() -> bool:
    """True when a real keyring backend is present."""
    if keyring is None:
        return False
    try:
        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except Exception:
        return False


# Backends raise a zoo of errors (D-Bus, locked collection, user dismissed the
# unlock prompt...). None of them should crash an upgrade, so each call treats
# any failure as "no stored password".
def load() -> str | None:
    if not available():
        return None
    try:
        return keyring.get_password(SERVICE, getpass.getuser())
    except Exception:
        return None


def save(password: str) -> bool:
    if not available():
        return False
    try:
        keyring.set_password(SERVICE, getpass.getuser(), password)
        return True
    except Exception:
        return False


def forget() -> bool:
    """Remove the stored password. Returns True if one was removed."""
    if not available():
        return False
    try:
        keyring.delete_password(SERVICE, getpass.getuser())
        return True
    except Exception:
        return False
