#!/usr/bin/env bash
# install.sh — build GhostGauge and install it to /Applications on your own Mac.
#
# A locally-built .app is never quarantined, so this avoids the Gatekeeper
# "Apple could not verify" prompt entirely — no signing or notarisation needed.
#
# NOTE: If you previously installed GhostGauge via Homebrew cask, run
#   brew uninstall --cask ghostgauge
# first, so Homebrew stops tracking the path that this script overwrites.

set -euo pipefail
cd "$(dirname "$0")"

TARGET="/Applications/GhostGauge.app"

# ---------------------------------------------------------------------------
# 1. Build
# ---------------------------------------------------------------------------
echo "==> Building GhostGauge.app..."
bash build.sh

# ---------------------------------------------------------------------------
# 2. Quit any running bundled-app instance
#    (Skips uv run app.py dev instances — only kills the packaged binary.)
# ---------------------------------------------------------------------------
echo "==> Stopping any running GhostGauge instance..."
pkill -f 'GhostGauge.app/Contents/MacOS/GhostGauge' 2>/dev/null || true

# ---------------------------------------------------------------------------
# 3. Replace the installed app
# ---------------------------------------------------------------------------
echo "==> Installing to $TARGET..."
rm -rf "$TARGET"
cp -R dist/GhostGauge.app "$TARGET"

# ---------------------------------------------------------------------------
# 4. Launch
# ---------------------------------------------------------------------------
echo "==> Launching GhostGauge..."
open "$TARGET"

echo ""
echo "==> Install complete: $TARGET"
