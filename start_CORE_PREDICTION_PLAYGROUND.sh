#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " Starting Core Prediction Playground"
echo "========================================"
echo ""

source venv/bin/activate
python -m streamlit run core_prediction_playground.py

echo ""
echo "Application closed."
read -p "Press Enter to close..."
