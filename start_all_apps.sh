#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " Starting All Shipside Database Apps"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./start_database.sh first)"
echo ""

source venv/bin/activate
python launcher.py

echo ""
echo "Applications closed."
read -p "Press Enter to close..."
