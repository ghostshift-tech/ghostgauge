#!/usr/bin/env bash
# install.sh — build GhostGauge and install it to /Applications on your own Mac.
#
# A locally-built .app is never quarantined, so this avoids the Gatekeeper
# "Apple could not verify" prompt entirely — no signing or notarisation needed.
#
# NOTE: If you previously installed GhostGauge via Homebrew cask, run
#   brew uninstall --cask ghostgauge
# first, so Homebrew stops tracking the path that this script overwrites.
#
# Overridable env vars (for testing):
#   GHOSTGAUGE_BUILD_CMD   — replace the build command (default: bash build.sh)
#   GHOSTGAUGE_TARGET      — override install path (default: /Applications/GhostGauge.app)
#   GHOSTGAUGE_NO_LAUNCH   — set to 1 to skip login-item + open (dry-run safety)

set -euo pipefail
cd "$(dirname "$0")"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BUILD_CMD="${GHOSTGAUGE_BUILD_CMD:-bash build.sh}"
TARGET="${GHOSTGAUGE_TARGET:-/Applications/GhostGauge.app}"
LOG="/tmp/ghostgauge-install.log"

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
VERSION=$(grep '^VERSION = ' app.py | head -1 | sed 's/VERSION = "//;s/"//')

# ---------------------------------------------------------------------------
# TTY detection
# ---------------------------------------------------------------------------
if [ -t 1 ]; then USE_TTY=1; else USE_TTY=0; fi

# ---------------------------------------------------------------------------
# Color setup (bash 3.2 compatible — no associative arrays, no ${var^^})
# ---------------------------------------------------------------------------
ORANGE="" DIM="" GREEN="" RED="" RESET=""
if [ "$USE_TTY" = "1" ]; then
  case "${COLORTERM:-}" in
    *truecolor*|*24bit*)
      ORANGE=$'\033[38;2;215;135;95m'
      ;;
    *)
      ORANGE=$'\033[38;5;173m'
      ;;
  esac
  DIM=$'\033[2m'
  GREEN=$'\033[32m'
  RED=$'\033[31m'
  RESET=$'\033[0m'
fi

# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------
SPIN_CHARS=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧')
SPIN_IDX=0
next_spin() {
  printf '%s' "${SPIN_CHARS[$SPIN_IDX]}"
  SPIN_IDX=$(( (SPIN_IDX + 1) % 8 ))
}

# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------
_LAST_NON_TTY_PCT=-1

progress() {
  local pct="$1"
  local label="$2"
  local filled empty bar i

  # Clamp
  [ "$pct" -lt 0 ] && pct=0
  [ "$pct" -gt 100 ] && pct=100

  if [ "$USE_TTY" = "1" ]; then
    filled=$(( pct * 30 / 100 ))
    empty=$(( 30 - filled ))

    bar=""
    i=0
    while [ "$i" -lt "$filled" ]; do
      bar="${bar}${ORANGE}█${RESET}"
      i=$(( i + 1 ))
    done
    i=0
    while [ "$i" -lt "$empty" ]; do
      bar="${bar}${DIM}░${RESET}"
      i=$(( i + 1 ))
    done

    printf '\r  %s  %3d%%  %s\033[K' "$bar" "$pct" "$label"
  else
    if [ "$pct" != "$_LAST_NON_TTY_PCT" ]; then
      printf '[ %3d%%] %s\n' "$pct" "$label"
      _LAST_NON_TTY_PCT="$pct"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
print_banner() {
  printf '\n'
  printf '%s' "$ORANGE"
  printf '   .-.      ____ _   _  ___  ____ _____ ____    _   _   _  ____ _____\n'
  printf '  (o o)    / ___| | | |/ _ \/ ___|_   _/ ___|  / \ | | | |/ ___| ____|\n'
  printf '  | O \   | |  _| |_| | | | \___ \ | || |  _  / _ \| | | | |  _|  _|\n'
  printf '   \   \  | |_| |  _  | |_| |___) || || |_| |/ ___ \ |_| | |_| | |___\n'
  printf "    \`~~~'  \\____|_| |_|\\___/|____/ |_| \\____/_/   \\_\\___/ \\____|_____|\n"
  printf '%s' "$RESET"
  printf '\n'
  printf '  %sClaude Code usage in your menubar — installing v%s%s\n' "$DIM" "$VERSION" "$RESET"
  printf '  %sLog: %s%s\n' "$DIM" "$LOG" "$RESET"
  printf '\n'
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print_banner

# Truncate log
: > "$LOG"

progress 2 "Starting build..."

# errexit must be off when the async build is launched AND when wait returns,
# or bash 3.2 aborts at `wait` on failure (before build_status is captured)
# and collapses the real exit code to 1.
set +e
eval "$BUILD_CMD" >> "$LOG" 2>&1 &
build_pid=$!

current_pct=2
spin_label="Building GhostGauge.app"

# Poll loop: check log for the highest marker reached, update progress
while kill -0 "$build_pid" 2>/dev/null; do
  new_pct=$current_pct

  if grep -q 'Ad-hoc signing' "$LOG" 2>/dev/null; then
    new_pct=80; spin_label="Ad-hoc signing"
  elif grep -q 'Writing source_path.txt' "$LOG" 2>/dev/null; then
    new_pct=77; spin_label="Writing bundle metadata"
  elif grep -q 'Build SUCCESS' "$LOG" 2>/dev/null; then
    new_pct=74; spin_label="Build complete"
  elif grep -q 'Building GhostGauge.app with py2app' "$LOG" 2>/dev/null; then
    new_pct=42; spin_label="Running py2app (takes a while)"
  elif grep -q 'Cleaning previous build/dist' "$LOG" 2>/dev/null; then
    new_pct=38; spin_label="Cleaning artifacts"
  elif grep -q 'Checking py2app patch' "$LOG" 2>/dev/null; then
    new_pct=34; spin_label="Checking py2app patch"
  elif grep -q 'Installing dependencies' "$LOG" 2>/dev/null; then
    new_pct=18; spin_label="Installing dependencies"
  elif grep -q 'Recreating .venv' "$LOG" 2>/dev/null; then
    new_pct=8; spin_label="Creating virtual env"
  fi

  if [ "$new_pct" -gt "$current_pct" ]; then
    current_pct=$new_pct
  fi

  spin_char=$(next_spin)
  progress "$current_pct" "${spin_label} ${spin_char}"
  sleep 1
done

wait "$build_pid"
build_status=$?
set -e

if [ "$build_status" -ne 0 ]; then
  [ "$USE_TTY" = "1" ] && printf '\n'
  printf '%s✗ Build failed (exit %d)%s\n' "$RED" "$build_status" "$RESET"
  printf 'Last 30 lines of build log (%s):\n' "$LOG"
  tail -n 30 "$LOG"
  exit "$build_status"
fi

progress 82 "Build complete"

# ---------------------------------------------------------------------------
# 2. Quit any running bundled-app instance (non-fatal)
# ---------------------------------------------------------------------------
progress 85 "Stopping any running GhostGauge instance..."
pkill -f 'GhostGauge.app/Contents/MacOS/GhostGauge' 2>/dev/null || true

# ---------------------------------------------------------------------------
# 3. Replace the installed app
# ---------------------------------------------------------------------------
progress 88 "Installing to ${TARGET}..."
rm -rf "$TARGET"
cp -R dist/GhostGauge.app "$TARGET"

progress 90 "Installed to ${TARGET}"

# ---------------------------------------------------------------------------
# 4. Register as a Login Item (auto-start at login), idempotent
# ---------------------------------------------------------------------------
progress 93 "Registering login item..."
LOGIN_OK=0
if [ "${GHOSTGAUGE_NO_LAUNCH:-0}" != "1" ]; then
  osascript -e 'tell application "System Events" to delete (every login item whose name is "GhostGauge")' >/dev/null 2>&1 || true
  if osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/GhostGauge.app", hidden:false}' >/dev/null 2>&1; then
    LOGIN_OK=1
  fi
fi

progress 95 "Login item step complete"

# ---------------------------------------------------------------------------
# 5. Launch
# ---------------------------------------------------------------------------
progress 98 "Launching GhostGauge..."
if [ "${GHOSTGAUGE_NO_LAUNCH:-0}" != "1" ]; then
  open "$TARGET"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
progress 100 "Done"
[ "$USE_TTY" = "1" ] && printf '\n'
printf '\n'

printf '%s✓ Installed:%s %s\n' "$GREEN" "$RESET" "$TARGET"

if [ "$LOGIN_OK" = "1" ]; then
  printf '%s✓ Login item registered%s — starts automatically at login\n' "$GREEN" "$RESET"
else
  if [ "${GHOSTGAUGE_NO_LAUNCH:-0}" = "1" ]; then
    printf '%s(login item skipped)%s\n' "$DIM" "$RESET"
  else
    printf '%s(login item could not be registered automatically — add in%s\n' "$DIM" "$RESET"
    printf '%s System Settings → General → Login Items)%s\n' "$DIM" "$RESET"
  fi
fi

if [ "${GHOSTGAUGE_NO_LAUNCH:-0}" != "1" ]; then
  printf '%s✓ Launched%s — check your menubar (top right)\n' "$GREEN" "$RESET"
else
  printf '%s(launch skipped)%s\n' "$DIM" "$RESET"
fi

printf '\n'
