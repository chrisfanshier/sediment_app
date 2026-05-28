#!/bin/bash
echo "========================================"
echo " Starting Recoil Fitting Tool"
echo "========================================"
echo ""
echo "Make sure database is running!"
echo "(If not, run ./start_database.sh first)"
echo ""
cd ~/ShipsideDB/app/scripts
source venv/bin/activate
python -m recoil_tool
echo "Application closed."
