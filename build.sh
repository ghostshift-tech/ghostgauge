#!/usr/bin/env bash
set -euo pipefail

# Always run from the directory that contains this script
cd "$(dirname "$0")"

echo "==> Working directory: $(pwd)"

# ---------------------------------------------------------------------------
# 1. Recreate the build venv with uv + Python 3.12
# ---------------------------------------------------------------------------
echo "==> Recreating .venv with uv (Python 3.12)..."
rm -rf .venv
uv venv --python 3.12 .venv

# ---------------------------------------------------------------------------
# 2. Install dependencies
# ---------------------------------------------------------------------------
echo "==> Installing dependencies..."
uv pip install --python .venv rumps httpx keyring py2app

# ---------------------------------------------------------------------------
# 3. Apply py2app patch (idempotent)
#    py2app 0.28.x calls zlib.__file__ unconditionally; the uv-managed Python
#    3.12 standalone build has zlib compiled in with no __file__, causing a
#    crash. Wrap the copy block in a hasattr guard.
# ---------------------------------------------------------------------------
echo "==> Checking py2app patch..."

PATCH_MARKER="hasattr(zlib, '__file__') and zlib.__file__ is not None"
BUILD_APP_PY=$(find .venv -path "*/py2app/build_app.py" | head -1)

if [[ -z "$BUILD_APP_PY" ]]; then
    echo "ERROR: could not find py2app/build_app.py inside .venv" >&2
    exit 1
fi

if grep -qF "$PATCH_MARKER" "$BUILD_APP_PY"; then
    echo "==> py2app patch: already patched — skipping"
else
    echo "==> py2app patch: applying..."
    python3 - "$BUILD_APP_PY" <<'PYEOF'
import sys, re

path = sys.argv[1]
src = open(path, encoding="utf-8").read()

# Target: any line that copies zlib via zlib.__file__ but is NOT yet guarded.
# Pattern matches lines like:
#   shutil.copy2(zlib.__file__, ...)
# or any other expression that dereferences zlib.__file__ outside a guard.
# We locate the enclosing logical block (the line + possible continuation)
# and wrap it in an if-guard.

# Find the line number and content of the first unguarded zlib.__file__ usage
lines = src.splitlines(keepends=True)
target_idx = None
for i, line in enumerate(lines):
    if "zlib.__file__" in line and "hasattr(zlib" not in line:
        target_idx = i
        break

if target_idx is None:
    print("WARNING: no unguarded zlib.__file__ found — nothing to patch")
    sys.exit(0)

# Determine existing indentation
original_line = lines[target_idx]
indent = len(original_line) - len(original_line.lstrip())
ind = " " * indent

# Wrap the single line in a guard
guarded = (
    f"{ind}if hasattr(zlib, '__file__') and zlib.__file__ is not None:\n"
    f"    {original_line}"  # adds 4-space extra indent
)
lines[target_idx] = guarded

open(path, "w", encoding="utf-8").write("".join(lines))
print(f"Patched line {target_idx + 1} in {path}")
PYEOF
    echo "==> py2app patch: applied successfully"
fi

# ---------------------------------------------------------------------------
# 4. Clean previous build artifacts
# ---------------------------------------------------------------------------
echo "==> Cleaning previous build/dist..."
rm -rf build dist

# ---------------------------------------------------------------------------
# 5. Build the .app
# ---------------------------------------------------------------------------
echo "==> Building GhostGauge.app with py2app..."
.venv/bin/python setup.py py2app

# ---------------------------------------------------------------------------
# 6. Report result
# ---------------------------------------------------------------------------
APP_PATH="dist/GhostGauge.app"
if [[ -d "$APP_PATH" ]]; then
    SIZE=$(du -sh "$APP_PATH" | cut -f1)
    echo ""
    echo "==> Build SUCCESS"
    echo "    Path : $(pwd)/$APP_PATH"
    echo "    Size : $SIZE"
else
    echo "ERROR: dist/GhostGauge.app not found after build" >&2
    exit 1
fi
