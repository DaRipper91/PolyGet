#!/usr/bin/env bash
# Install the PolyGet .desktop entry and icons into the current user's home.
# Re-runnable; safe to call after moving or renaming the repo.
#
#   ./scripts/install-desktop.sh          # install
#   ./scripts/install-desktop.sh --uninstall

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_SRC="$REPO_ROOT/assets/polyget.desktop"
ICON_SRC_DIR="$REPO_ROOT/assets/icons"

APPLICATIONS_DIR="$HOME/.local/share/applications"
ICON_THEME_DIR="$HOME/.local/share/icons/hicolor"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "error: no interpreter at $PYTHON_BIN" >&2
    echo "hint: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

uninstall() {
    rm -fv "$APPLICATIONS_DIR/polyget.desktop"
    for size in 16 32 48 64 128 256 512; do
        rm -fv "$ICON_THEME_DIR/${size}x${size}/apps/polyget.png"
    done
    rm -fv "$ICON_THEME_DIR/scalable/apps/polyget.svg"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPLICATIONS_DIR" || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$ICON_THEME_DIR" || true
    echo "PolyGet desktop entry removed."
}

install() {
    mkdir -p "$APPLICATIONS_DIR" "$ICON_THEME_DIR/scalable/apps"

    # The desktop file hardcodes the repo path, so bake this checkout's paths in
    # rather than relying on the copy in assets/.
    sed \
        -e "s|^Exec=.*|Exec=$PYTHON_BIN $REPO_ROOT/run.py %f|" \
        -e "s|^TryExec=.*|TryExec=$PYTHON_BIN|" \
        "$DESKTOP_SRC" > "$APPLICATIONS_DIR/polyget.desktop"
    chmod 644 "$APPLICATIONS_DIR/polyget.desktop"

    cp "$ICON_SRC_DIR/polyget.svg" "$ICON_THEME_DIR/scalable/apps/polyget.svg"
    for size in 16 32 48 64 128 256 512; do
        mkdir -p "$ICON_THEME_DIR/${size}x${size}/apps"
        cp "$ICON_SRC_DIR/polyget-$size.png" "$ICON_THEME_DIR/${size}x${size}/apps/polyget.png"
    done

    command -v update-desktop-database >/dev/null && update-desktop-database "$APPLICATIONS_DIR" || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$ICON_THEME_DIR" || true

    echo "Installed:"
    echo "  entry  $APPLICATIONS_DIR/polyget.desktop"
    echo "  icons  $ICON_THEME_DIR/{scalable,16x16..512x512}/apps/polyget.*"
    echo
    echo "Pointed at: $REPO_ROOT/run.py"
    echo "Re-run this script after moving the repo to refresh the paths."
}

case "${1:-install}" in
    --uninstall|-u) uninstall ;;
    *) install ;;
esac
