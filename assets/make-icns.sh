#!/usr/bin/env bash
# Generates GhostGauge.icns at the repo root.
# Usage: bash assets/make-icns.sh   (from any directory)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PNG_SRC="$SCRIPT_DIR/icon_1024.png"
ICONSET="$SCRIPT_DIR/GhostGauge.iconset"
ICNS_OUT="$REPO_ROOT/GhostGauge.icns"

echo "==> Generating 1024×1024 source PNG…"
uv run "$SCRIPT_DIR/make_icon.py"

echo "==> Building iconset…"
rm -rf "$ICONSET"
mkdir "$ICONSET"

# sips usage: sips -z <height> <width> src --out dst
sips -z 16   16   "$PNG_SRC" --out "$ICONSET/icon_16x16.png"      2>/dev/null
sips -z 32   32   "$PNG_SRC" --out "$ICONSET/icon_16x16@2x.png"   2>/dev/null
sips -z 32   32   "$PNG_SRC" --out "$ICONSET/icon_32x32.png"       2>/dev/null
sips -z 64   64   "$PNG_SRC" --out "$ICONSET/icon_32x32@2x.png"    2>/dev/null
sips -z 128  128  "$PNG_SRC" --out "$ICONSET/icon_128x128.png"     2>/dev/null
sips -z 256  256  "$PNG_SRC" --out "$ICONSET/icon_128x128@2x.png"  2>/dev/null
sips -z 256  256  "$PNG_SRC" --out "$ICONSET/icon_256x256.png"      2>/dev/null
sips -z 512  512  "$PNG_SRC" --out "$ICONSET/icon_256x256@2x.png"  2>/dev/null
sips -z 512  512  "$PNG_SRC" --out "$ICONSET/icon_512x512.png"      2>/dev/null
sips -z 1024 1024 "$PNG_SRC" --out "$ICONSET/icon_512x512@2x.png" 2>/dev/null

echo "==> Converting iconset to .icns…"
iconutil -c icns "$ICONSET" -o "$ICNS_OUT"

echo "==> Cleaning up temporary iconset…"
rm -rf "$ICONSET"

ICNS_SIZE=$(du -sh "$ICNS_OUT" | cut -f1)
echo ""
echo "==> SUCCESS"
echo "    Path : $ICNS_OUT"
echo "    Size : $ICNS_SIZE"
