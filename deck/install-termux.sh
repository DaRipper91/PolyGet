#!/usr/bin/env bash
# install-termux.sh — Install Pixel Control Deck into Termux userland
# Target: Google Pixel 10 Pro (Tensor G5 blazer · Android 17 / Termux)
set -euo pipefail

SRC_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# Target detection
TERMUX_PREFIX="/data/data/com.termux/files/usr"
PREFIX="$TERMUX_PREFIX"
INSTALL_SHORTCUT=1

while (( $# )); do
  case "$1" in
    --prefix=*) PREFIX="${1#*=}" ;;
    --user)     PREFIX="${HOME}/.local" ;;
    --proot)    PREFIX="/usr/local" ;;
    -h|--help)
      printf 'Usage: %s [--prefix=PATH | --user | --proot]\n' "$0"
      printf 'Defaults to %s (Termux native prefix)\n' "$TERMUX_PREFIX"
      exit 0
      ;;
    *) printf 'Unknown flag: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

INSTALL_ROOT="${DESTDIR:-}${PREFIX}"
printf '==> Installing Pixel Control Deck into: %s\n' "$INSTALL_ROOT"

# Create directories
install -d "$INSTALL_ROOT/lib/pixel-deck"
install -d "$INSTALL_ROOT/lib/pixel-deck/lib"
install -d "$INSTALL_ROOT/bin"
install -d "$INSTALL_ROOT/share/icons/hicolor/scalable/apps"
install -d "$INSTALL_ROOT/share/applications"

# Copy engine and catalog
install -Dm755 "$SRC_DIR/pixel-deck.py" "$INSTALL_ROOT/lib/pixel-deck/pixel-deck.py"
install -Dm755 "$SRC_DIR/configure-apt.sh" "$INSTALL_ROOT/lib/pixel-deck/configure-apt.sh"
install -Dm644 "$SRC_DIR/termux-repos.catalog" "$INSTALL_ROOT/lib/pixel-deck/termux-repos.catalog"
install -Dm644 "$SRC_DIR/apt.conf" "$INSTALL_ROOT/lib/pixel-deck/apt.conf"
install -Dm644 "$SRC_DIR/lib/walk.sh" "$INSTALL_ROOT/lib/pixel-deck/lib/walk.sh"
install -Dm644 "$SRC_DIR/lib/dryrun-gate.sh" "$INSTALL_ROOT/lib/pixel-deck/lib/dryrun-gate.sh"

# Create pixel-deck binary launcher
cat > "$INSTALL_ROOT/bin/pixel-deck" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
LAUNCHER_SOURCE="$(readlink -f "${BASH_SOURCE[0]}")"
LAUNCHER_DIR=$(cd -- "$(dirname -- "$LAUNCHER_SOURCE")" && pwd)
DECK_LIB="$LAUNCHER_DIR/../lib/pixel-deck"
# Resolve Python: Termux python3 > system python3
PY_BIN=""
if [[ -x "/data/data/com.termux/files/usr/bin/python3" ]]; then
  PY_BIN="/data/data/com.termux/files/usr/bin/python3"
elif command -v python3 >/dev/null; then
  PY_BIN="$(command -v python3)"
else
  printf 'ERROR: python3 not found. Run: pkg install python\n' >&2
  exit 1
fi
exec "$PY_BIN" "$DECK_LIB/pixel-deck.py" "$@"
LAUNCHER
chmod 755 "$INSTALL_ROOT/bin/pixel-deck"

# Create termux-deck symlink
ln -sf "pixel-deck" "$INSTALL_ROOT/bin/termux-deck"

# Create configure-apt binary launcher
cat > "$INSTALL_ROOT/bin/configure-apt" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
LAUNCHER_SOURCE="$(readlink -f "${BASH_SOURCE[0]}")"
LAUNCHER_DIR=$(cd -- "$(dirname -- "$LAUNCHER_SOURCE")" && pwd)
exec "$LAUNCHER_DIR/../lib/pixel-deck/configure-apt.sh" "$@"
LAUNCHER
chmod 755 "$INSTALL_ROOT/bin/configure-apt"

# Icons and Desktop entry
install -Dm644 "$SRC_DIR/pixel-deck.svg" "$INSTALL_ROOT/share/icons/hicolor/scalable/apps/pixel-deck.svg"
install -Dm644 "$SRC_DIR/pixel-deck.desktop" "$INSTALL_ROOT/share/applications/pixel-deck.desktop"

# Termux widget shortcut (for Termux:Widget home screen shortcut)
SHORTCUTS_DIR="${HOME}/.shortcuts"
if [[ -d "$SHORTCUTS_DIR" || "$INSTALL_SHORTCUT" -eq 1 ]]; then
  mkdir -p "$SHORTCUTS_DIR"
  cat > "$SHORTCUTS_DIR/pixel-deck" <<'SHORTCUT'
#!/data/data/com.termux/files/usr/bin/bash
exec pixel-deck
SHORTCUT
  chmod 755 "$SHORTCUTS_DIR/pixel-deck"
  printf '✓ Installed Termux widget shortcut to %s/pixel-deck\n' "$SHORTCUTS_DIR"
fi

# Ensure /usr/local/bin symlinks exist for PRoot distro access if prefix is Termux
if [[ "$PREFIX" == "$TERMUX_PREFIX" && -d "/usr/local/bin" && -w "/usr/local/bin" ]]; then
  ln -sf "$INSTALL_ROOT/bin/pixel-deck" "/usr/local/bin/pixel-deck"
  ln -sf "$INSTALL_ROOT/bin/termux-deck" "/usr/local/bin/termux-deck"
  ln -sf "$INSTALL_ROOT/bin/configure-apt" "/usr/local/bin/configure-apt"
  printf '✓ Linked launchers into /usr/local/bin for PRoot container access\n'
fi

printf '\n✓ Successfully installed Pixel Control Deck to %s\n' "$INSTALL_ROOT"
printf '  Run: pixel-deck (or termux-deck)\n'
printf '  Headless CLI: configure-apt list\n'
