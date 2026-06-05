#!/bin/bash
# Double-clickable installer button for GhostGauge.
# Finder runs this in Terminal on double-click. It builds the app locally
# (locally built = NOT quarantined → no Gatekeeper prompt) and installs it
# to /Applications, then launches it.
#
# Note: keep this file next to install.sh / build.sh / app.py in the repo.

cd "$(dirname "$0")" || exit 1

echo "==> Installing GhostGauge (building locally, no Gatekeeper prompt)…"
echo

bash ./install.sh
status=$?

echo
if [ "$status" -eq 0 ]; then
  echo "✅ GhostGauge installed to /Applications and launched."
else
  echo "❌ Install failed (exit $status). Scroll up for the error."
fi
echo "Press any key to close this window…"
read -n 1 -s
echo
