#!/bin/bash
# Build a single-file Dragognosificator executable (macOS / Linux).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

echo "Building Dragognosificator..."
python3 -m pip install -q -r dredge_standalone/requirements.txt pyinstaller
python3 -m PyInstaller --clean --noconfirm dredge_standalone/packaging/dragognosificator.spec
echo "Done: $ROOT/dist/Dragognosificator"
