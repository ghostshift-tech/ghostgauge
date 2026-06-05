#!/usr/bin/env bash
# bump-version.sh — bumps VERSION in app.py and setup.py, commits, tags, and pushes.
# macOS (BSD sed) — uses sed -i '' syntax.

set -euo pipefail

# Always run from the repo root regardless of where the script is called from.
cd "$(dirname "$0")"

# ---------------------------------------------------------------------------
# 1. Read current version from app.py
# ---------------------------------------------------------------------------
CURRENT=$(grep -E '^VERSION = ' app.py | sed -E 's/.*"([0-9]+\.[0-9]+\.[0-9]+)".*/\1/')

if [[ -z "$CURRENT" ]]; then
  echo "ERROR: Could not detect current version from app.py" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Prompt for new version
# ---------------------------------------------------------------------------
read -rp "Current version: $CURRENT — enter new version (e.g. 0.1.2): " NEW

# ---------------------------------------------------------------------------
# 3. Validate the new version
# ---------------------------------------------------------------------------

# Must match semver-like X.Y.Z
if [[ ! "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: '$NEW' is not a valid version (expected X.Y.Z format)" >&2
  exit 1
fi

# Must differ from current
if [[ "$NEW" == "$CURRENT" ]]; then
  echo "ERROR: New version '$NEW' is the same as the current version" >&2
  exit 1
fi

# Tag must not already exist
if git rev-parse -q --verify "refs/tags/v$NEW" > /dev/null 2>&1; then
  echo "ERROR: Git tag 'v$NEW' already exists" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 4. Apply version replacements (literal substitution to avoid false matches)
# ---------------------------------------------------------------------------
sed -i '' "s/^VERSION = \"$CURRENT\"/VERSION = \"$NEW\"/" app.py
sed -i '' "s/'CFBundleVersion': '$CURRENT'/'CFBundleVersion': '$NEW'/" setup.py
sed -i '' "s/'CFBundleShortVersionString': '$CURRENT'/'CFBundleShortVersionString': '$NEW'/" setup.py

# ---------------------------------------------------------------------------
# 5. Verify all three occurrences were actually updated
# ---------------------------------------------------------------------------
VERIFY_FAILED=0

if ! grep -qE "^VERSION = \"$NEW\"" app.py; then
  echo "ERROR: VERSION in app.py was not updated (still shows old value)" >&2
  VERIFY_FAILED=1
fi

if ! grep -q "'CFBundleVersion': '$NEW'" setup.py; then
  echo "ERROR: CFBundleVersion in setup.py was not updated" >&2
  VERIFY_FAILED=1
fi

if ! grep -q "'CFBundleShortVersionString': '$NEW'" setup.py; then
  echo "ERROR: CFBundleShortVersionString in setup.py was not updated" >&2
  VERIFY_FAILED=1
fi

if [[ "$VERIFY_FAILED" -eq 1 ]]; then
  echo "Reverting changes to app.py and setup.py..." >&2
  git checkout -- app.py setup.py
  exit 1
fi

# ---------------------------------------------------------------------------
# 6. Show the diff so the user can review what changed
# ---------------------------------------------------------------------------
echo ""
echo "=== Changes ==="
git --no-pager diff app.py setup.py
echo "==============="
echo ""

# ---------------------------------------------------------------------------
# 7. Confirm before doing anything irreversible
# ---------------------------------------------------------------------------
read -rp "Commit, tag v$NEW, and push to GitHub? [y/N] " ANS

if [[ ! "$ANS" =~ ^[yY]$ ]]; then
  git checkout -- app.py setup.py
  echo "Aborted, no changes made."
  exit 0
fi

# ---------------------------------------------------------------------------
# 8. Commit, tag, and push
# ---------------------------------------------------------------------------
git add app.py setup.py
git commit -m "chore: bump version to $NEW"
git tag -a "v$NEW" -m "GhostGauge v$NEW"
git push
git push origin "v$NEW"

# ---------------------------------------------------------------------------
# 9. Create a notes-only GitHub Release (no binary attached — keeps the
#    build-local / no-Gatekeeper model). Non-fatal: the tag is already pushed.
# ---------------------------------------------------------------------------
if command -v gh > /dev/null 2>&1; then
  gh release create "v$NEW" --generate-notes --title "GhostGauge v$NEW" \
    || echo "warn: gh release create failed (tag v$NEW is still pushed)"
else
  echo "warn: gh CLI not found — skipped GitHub Release (tag v$NEW is pushed)"
fi

# ---------------------------------------------------------------------------
# 10. Success summary
# ---------------------------------------------------------------------------
echo ""
echo "Done!"
echo "  Version : $NEW"
echo "  Tag     : v$NEW"
echo "  Releases: https://github.com/ghostshift-tech/ghostgauge/releases/tag/v$NEW"
