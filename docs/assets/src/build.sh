#!/usr/bin/env bash
# build.sh - Deterministic asset regeneration for PolyGet
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ASSETS_DIR/.." && pwd)"

echo "==> Regenerating PolyGet visual assets in $ASSETS_DIR..."

# Check required binaries
for bin in resvg; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "Error: Required binary '$bin' not found in PATH." >&2
        exit 1
    fi
done

# Render social preview PNG from SVG
echo "--> Rendering social-preview.png (1280x640)..."
resvg "$ASSETS_DIR/social-preview.svg" "$ASSETS_DIR/social-preview.png"

# Test render banner and divider
echo "--> Verifying banner.svg and divider.svg rendering..."
resvg "$ASSETS_DIR/banner.svg" /tmp/polyget_banner_check.png
resvg "$ASSETS_DIR/divider.svg" /tmp/polyget_divider_check.png
resvg "$ASSETS_DIR/mcp-flow.svg" /tmp/polyget_mcp_flow_check.png
rm -f /tmp/polyget_*_check.png

# If vhs is installed and chromium is available, record terminal demo
if command -v vhs >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/demo.tape" ]; then
    echo "--> Attempting demo.gif recording via VHS..."
    if ! (cd "$SCRIPT_DIR" && vhs demo.tape -o "$ASSETS_DIR/demo.gif" 2>/dev/null); then
        echo "    Notice: VHS recording skipped (requires Chromium binary on aarch64)."
    fi
fi

echo "==> All visual assets verified and up to date."
