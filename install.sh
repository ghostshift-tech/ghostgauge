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
# 4. Register as a Login Item (auto-start at login), idempotent
#    Removes any existing "GhostGauge" entry first so it never duplicates.
#    First run may ask Terminal for Automation permission to control
#    System Events — that's a one-time macOS prompt.
# ---------------------------------------------------------------------------
echo "==> Registering Login Item (auto-start at login)..."
osascript -e 'tell application "System Events" to delete (every login item whose name is "GhostGauge")' >/dev/null 2>&1 || true
if osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/GhostGauge.app", hidden:false}' >/dev/null 2>&1; then
  echo "    added to Login Items (System Settings → General → Login Items)"
else
  echo "    (could not register automatically — add it manually in"
  echo "     System Settings → General → Login Items, or allow the Automation prompt and re-run)"
fi

# ---------------------------------------------------------------------------
# 5. Launch
# ---------------------------------------------------------------------------
echo "==> Launching GhostGauge..."
open "$TARGET"

echo ""
echo "==> Install complete: $TARGET"
echo "    GhostGauge will now start automatically at login."
