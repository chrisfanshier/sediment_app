#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " Starting Recoil Fitting Tool"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./start_database.sh first)"
echo ""

source venv/bin/activate
python -m recoil_tool

echo ""
echo "Application closed."
read -p "Press Enter to close..."
